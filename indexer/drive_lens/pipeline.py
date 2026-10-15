"""The two jobs: list the shared tree, then process what's new.

`list_drive` walks the share link and records every folder and file (locked
folders included). `process` takes files still to do, in batches: preview →
description (threads) → vectors (one batch on the GPU/CPU) → one transaction.
Everything is resumable: stop at any point, run again, it carries on."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import store
from .describe import DescribeError, Describer
from .drive import AnonymousSource, Locked, WalkReport, kind_of, walk
from .embed import Embedder
from .fetch import Prepared, prepare


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def list_drive(source: AnonymousSource, conn, root_id: str, *, pause: float = 0.3) -> dict:
    stamp = store.now()
    report = WalkReport()
    counts = {"new": 0, "changed": 0, "moved": 0, "same": 0}
    t0 = time.time()

    def on_folder(fid: str, path: str, parent: str | None) -> None:
        store.upsert_folder(conn, fid, path, parent, stamp)
        conn.commit()
        if report.folders % 25 == 0:
            log(f"  {report.folders} folders, {report.files} files, {len(report.locked)} locked  ({time.time() - t0:.0f}s)")

    for item in walk(source, root_id, pause=pause, on_folder=on_folder, report=report):
        e = item.entry
        counts[store.upsert_file(conn, id=e.id, name=e.name, mime=e.mime, kind=kind_of(e.mime, e.name), size=e.size, md5=e.md5,
                                 modified=e.modified, path=item.path, parent_id=item.parent_id, stamp=stamp)] += 1
    for fid, path, reason in report.locked:
        store.upsert_folder(conn, fid, path, None, stamp, locked=reason)
    removed = store.remove_unseen(conn, stamp)
    store.set_meta(conn, root_id=root_id, listed_at=stamp, source=source.name)
    conn.commit()
    return {"folders": report.folders, "files": report.files, "locked": len(report.locked), "removed": removed, **counts,
            "seconds": round(time.time() - t0)}


@dataclass
class Outcome:
    row: object
    prepared: Prepared | None = None
    analysis: dict | None = None
    usage: list | None = None
    seconds: float = 0.0
    error: str = ""
    skipped: bool = False


def _context(row) -> dict:
    folder = row["path"].rsplit("/", 1)[0] if "/" in row["path"] else ""
    return {"file name": row["name"], "folder": folder, "kind": row["kind"] if row["kind"] != "image" else ""}


def _work(row, source: AnonymousSource, describer: Describer | None) -> Outcome:
    out = Outcome(row=row)
    try:
        out.prepared = prepare(source, row["id"], row["kind"])
    except Locked as e:
        out.error, out.skipped = f"no preview: {e}", True
        return out
    except Exception as e:
        out.error = f"preview: {type(e).__name__}: {e}"
        return out
    if describer and out.prepared.image is not None:
        t = time.time()
        try:
            out.analysis, out.usage = describer.describe(out.prepared.jpeg, _context(row))
        except DescribeError as e:
            out.error, out.usage = f"describe: {e}", e.usage
        except Exception as e:
            out.error = f"describe: {type(e).__name__}: {e}"
        out.seconds = time.time() - t
    return out


def process(conn, source: AnonymousSource, embedder: Embedder, describer: Describer | None, *, kinds: list[str],
            limit: int | None = None, sample: int | None = None, batch: int = 16, concurrency: int = 4,
            retry_errors: bool = False) -> dict:
    rows = store.todo(conn, kinds=kinds, limit=limit, retry_errors=retry_errors, sample=sample)
    total = len(rows)
    log(f"{total} files to process ({', '.join(kinds)}); describer: {describer.label if describer else 'off'}; embedder: {embedder.label}")
    store.set_meta(conn, embed_model=embedder.label, describe_model=describer.label if describer else "", dims=store.DIMS)
    done = failed = skipped = 0
    t0 = time.time()
    embed_secs = 0.0
    chunks = [rows[i:i + batch] for i in range(0, total, batch)]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        submit = lambda chunk: [pool.submit(_work, r, source, describer) for r in chunk]
        pending = submit(chunks[0]) if chunks else []
        for ci, chunk in enumerate(chunks):
            outs = [f.result() for f in pending]
            # The next batch's previews and descriptions run while this one embeds.
            pending = submit(chunks[ci + 1]) if ci + 1 < len(chunks) else []
            start = ci * batch
            ready = [o for o in outs if o.prepared and not o.error]
            # Files with no preview get no vector: a text vector of their name
            # outscored real pictures (text-text similarity runs higher than
            # text-image), and their name and folder are in the keyword index.
            visual = [o for o in ready if o.prepared.image is not None]
            vectors = []
            if visual:
                te = time.time()
                texts = [o.prepared.text if o.row["kind"] == "pdf" else "" for o in visual]
                vectors = embedder.vectors([o.prepared.image for o in visual], texts)
                embed_secs += time.time() - te
            vec_of = {id(o): v for o, v in zip(visual, vectors)}
            for o in outs:
                rid = o.row["rowid"]
                for i, u in enumerate(o.usage or []):
                    store.log_usage(conn, rid, describer.model if describer else "", describer.effort if describer else "", u,
                                    o.seconds if i == 0 else 0.0, ok=not o.error or i < len(o.usage) - 1, error=o.error if i == len(o.usage) - 1 else "")
                if o.error:
                    store.save_failure(conn, rid, o.error, skipped=o.skipped)
                    skipped += o.skipped
                    failed += not o.skipped
                    log(f"  ✗ {o.row['path'][-90:]}  {o.error[:160]}")
                    continue
                store.save_done(conn, rid, analysis=o.analysis, vector=vec_of.get(id(o)), thumb=o.prepared.thumb,
                                described_by=describer.label if describer else "", embedded_by=embedder.label)
                done += 1
                tok = sum((u.get("total_tokens") or 0) for u in o.usage or [])
                title = (o.analysis or {}).get("title", "")
                log(f"  ✓ {o.row['path'][-70:]}  [{o.seconds:.1f}s, {tok} tok] {title}")
            conn.commit()
            n = start + len(chunk)
            rate = (time.time() - t0) / n
            log(f"— {n}/{total} done in {time.time() - t0:.0f}s ({rate:.1f}s/file, embedding {embed_secs / max(1, done):.1f}s/file); "
                f"~{rate * (total - n) / 60:.0f} min left")
    return {"processed": total, "done": done, "failed": failed, "skipped": skipped, "seconds": round(time.time() - t0),
            "embed_seconds_per_file": round(embed_secs / max(1, done), 2)}
