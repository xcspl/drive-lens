"""drive-lens: index a shared Google Drive folder so any file can be found by what it shows.

  drive-lens list                 walk the share link, record every folder and file
  drive-lens run [--limit N]      sync with the Drive, then describe + embed what's new (resumable)
  drive-lens status               counts, locked folders, token use so far
  drive-lens search "words"       hybrid search from the terminal
  drive-lens export out.db        a compact copy of the index to share
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import config, store
from .drive import source_for

KINDS = ["image", "video", "pdf", "document", "other"]


def cmd_list(s: config.Settings, a) -> int:
    from .pipeline import list_drive
    conn = store.connect(s.db_path)
    src = source_for(s.google_api_key)
    print(f"Listing {s.share_link} ({src.name}) into {s.db_path}", file=sys.stderr)
    r = list_drive(src, conn, s.root_id, pause=a.pause, allow_mass_removal=a.allow_mass_removal)
    print(json.dumps(r, indent=1))
    return 0


def cmd_run(s: config.Settings, a) -> int:
    from .describe import Describer
    from .embed import Embedder
    from .pipeline import process
    conn = store.connect(s.db_path)
    if not a.no_list:
        # Sync with the Drive first: new files in, moves and renames applied, removed files out.
        from .pipeline import list_drive
        print(f"Syncing with {s.share_link} …", file=sys.stderr)
        sync = list_drive(source_for(s.google_api_key), conn, s.root_id, pause=a.pause)
        print("sync: " + json.dumps(sync), file=sys.stderr)
    if not conn.execute("SELECT 1 FROM files LIMIT 1").fetchone():
        raise SystemExit("The index is empty: nothing was found at the share link.")
    describer = None
    if not a.no_describe:
        if not s.model_key:
            raise SystemExit("MINIMAX_API_KEY is empty in .env (or pass --no-describe)")
        describer = Describer(base_url=s.base_url, api_key=s.model_key, model=s.model, effort=a.effort or s.effort)
    r = process(conn, source_for(s.google_api_key), Embedder(a.device), describer, kinds=a.kinds.split(","),
                limit=a.limit, sample=a.sample, batch=a.batch, concurrency=a.concurrency, retry_errors=a.retry_errors,
                retry_skipped=a.retry_skipped)
    print(json.dumps(r, indent=1))
    return 0


def usage_summary(st: dict) -> dict:
    u = st["usage"] or {}
    calls, ok = u.get("calls") or 0, u.get("ok") or 0
    if not calls:
        return {}
    pin, pout = u.get("pin") or 0, u.get("pout") or 0
    done = sum(v for k, v in st["by_kind_status"].items() if k.endswith(":done"))
    left = sum(v for k, v in st["by_kind_status"].items() if k.split(":")[0] in KINDS and k.endswith((":listed", ":error")))
    per = (pin + pout) / max(1, done)
    return {"calls": calls, "failed_calls": calls - ok, "input_tokens": pin, "output_tokens": pout,
            "reasoning_tokens": u.get("preason") or 0, "cached_input_tokens": u.get("pcached") or 0, "avg_seconds_per_call": round(u.get("secs") or 0, 1),
            "tokens_per_described_file": round(per), "files_left": left,
            "estimated_tokens_for_the_rest": round(per * left), "estimated_calls_for_the_rest": round(calls / max(1, done) * left)}


def cmd_status(s: config.Settings, a) -> int:
    if not s.db_path.exists():
        raise SystemExit(f"No index yet at {s.db_path}: run `drive-lens list`.")
    conn = store.connect(s.db_path, readonly=True)
    st = store.stats(conn)
    st["minimax"] = usage_summary(st)
    if not a.verbose:
        st["locked_folders"] = [f["path"] or f["id"] for f in st["locked_folders"]]
        st.pop("usage")
    print(json.dumps(st, indent=1, ensure_ascii=False))
    return 0


def cmd_search(s: config.Settings, a) -> int:
    from .search import search
    conn = store.connect(s.db_path, readonly=True)
    emb = None
    if not a.words_only:
        from .embed import Embedder
        emb = Embedder(a.device)
    for q in a.query:
        res = search(conn, q, embedder=emb, k=a.k)
        if a.json:
            print(json.dumps({"query": q, "results": res}, ensure_ascii=False))
            continue
        print(f"\n» {q}")
        for r in res:
            print(f"  {r['path']}\n     {r['title'] or '—'}  ·  {', '.join(r['why'])}\n     {r['url']}")
    return 0


def cmd_export(s: config.Settings, a) -> int:
    out = Path(a.out).expanduser()
    if out.exists():
        raise SystemExit(f"{out} exists")
    src = sqlite3.connect(s.db_path)
    src.execute("VACUUM INTO ?", (str(out),))
    src.close()
    conn = store.connect(out)
    if not a.keep_usage:
        conn.execute("DELETE FROM usage")
    conn.commit()
    conn.execute("VACUUM")
    print(f"{out}  {out.stat().st_size / 1e6:.1f} MB")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="drive-lens", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env", help="the .env file (default: nearest .env with DRIVE_LENS_SHARE_LINK)")
    p.add_argument("--link", help="Drive folder share link (overrides DRIVE_LENS_SHARE_LINK)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="walk the share link and record every folder and file")
    sp.add_argument("--pause", type=float, default=0.3, help="seconds between folder requests (default 0.3)")
    sp.add_argument("--allow-mass-removal", action="store_true",
                    help="remove files not seen even when that is more than 20%% of the index (normally refused)")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("run", help="describe and embed files not done yet")
    sp.add_argument("--limit", type=int, help="process at most N files (listing order)")
    sp.add_argument("--sample", type=int, help="process N files spread across the tree (a fixed pseudo-random pick)")
    sp.add_argument("--kinds", default=",".join(KINDS), help=f"comma list (default {','.join(KINDS)})")
    sp.add_argument("--batch", type=int, default=16)
    sp.add_argument("--concurrency", type=int, default=4, help="parallel previews/descriptions (default 4)")
    sp.add_argument("--effort", help="describer reasoning_effort: low|medium|high|xhigh|max (default from .env, else medium)")
    sp.add_argument("--device", help="cpu|mps|cuda (default: best available)")
    sp.add_argument("--no-describe", action="store_true", help="vectors only, no model calls")
    sp.add_argument("--retry-errors", action="store_true", help="also retry files that failed before (up to 3 attempts)")
    sp.add_argument("--retry-skipped", action="store_true", help="also retry files skipped before (e.g. no Drive preview)")
    sp.add_argument("--no-list", action="store_true", help="skip the sync with the Drive (by default every run lists it first)")
    sp.add_argument("--pause", type=float, default=0.3, help="seconds between folder requests while syncing (default 0.3)")
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("status", help="counts, locked folders, token use")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("search", help="hybrid search")
    sp.add_argument("query", nargs="+")
    sp.add_argument("-k", type=int, default=5)
    sp.add_argument("--words-only", action="store_true", help="keyword search only (no model)")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--device")
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("export", help="write a compact copy of the index for sharing")
    sp.add_argument("out")
    sp.add_argument("--keep-usage", action="store_true")
    sp.set_defaults(fn=cmd_export)

    a = p.parse_args(argv)
    return a.fn(config.load(a.env, a.link), a)


if __name__ == "__main__":
    sys.exit(main())
