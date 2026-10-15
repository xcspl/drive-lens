"""Hybrid search over an index: vector similarity (sqlite-vec) and keywords
(FTS5 over name, path, title, description, tags, text in the image), merged
with Reciprocal Rank Fusion. Files without a vector (documents, other) are
still found by their words."""

from __future__ import annotations

import json
import os
import re

from . import store
from .drive import file_url, folder_url

RRF_K = 60
POOL = 100
# Nearest vectors always exist, even for a query about nothing in the index
# (EmbeddingGemma 2 on the first 70 files: unrelated queries ~0.55-0.59, real
# matches mostly 0.6-0.76, a few weaker ones just under 0.6);
# below this cosine similarity a vector "match" earns no rank, so a file
# found by its words is not outranked by an unrelated picture.
MIN_SIM = float(os.environ.get("DRIVE_LENS_MIN_SIM", "0.5"))
STOP = set("a an and are as at be by for from has have in is it of on or the to was were with this that these those photo photos image images picture pictures file files show shows".split())
# bm25 weights, in files_fts column order: name, path, title, description, details, tags, text_in_image
WEIGHTS = (1.5, 2.0, 1.5, 1.0, 0.5, 1.5, 1.0)


def fts_query(q: str) -> str:
    words = [w for w in re.findall(r"\w+", q.lower()) if w not in STOP and len(w) > 1]
    return " OR ".join(f'"{w}"*' if len(w) >= 4 else f'"{w}"' for w in words)


def search(conn, q: str, *, embedder=None, k: int = 20) -> list[dict]:
    scores: dict[int, float] = {}
    why: dict[int, list[str]] = {}
    if embedder is not None and conn.execute("SELECT 1 FROM files_vec LIMIT 1").fetchone():
        qv = embedder.query(q)
        hits = conn.execute("SELECT rowid, distance FROM files_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                            (store.pack(qv), POOL)).fetchall()
        for rank, r in enumerate(h for h in hits if 1 - h[1] >= MIN_SIM):
            scores[r[0]] = scores.get(r[0], 0) + 1 / (RRF_K + rank)
            why.setdefault(r[0], []).append(f"meaning #{rank + 1} ({1 - r[1]:.2f})")
    fq = fts_query(q)
    if fq:
        rows = conn.execute(f"SELECT rowid, bm25(files_fts, {', '.join(map(str, WEIGHTS))}) s FROM files_fts WHERE files_fts MATCH ? ORDER BY s LIMIT ?",
                            (fq, POOL)).fetchall()
        for rank, r in enumerate(rows):
            scores[r[0]] = scores.get(r[0], 0) + 1 / (RRF_K + rank)
            why.setdefault(r[0], []).append(f"words #{rank + 1}")
    top = sorted(scores, key=scores.get, reverse=True)[:k]
    out = []
    for rid in top:
        f = conn.execute("SELECT * FROM files WHERE rowid = ?", (rid,)).fetchone()
        if f is None:
            continue
        out.append({
            "id": f["id"], "name": f["name"], "path": f["path"], "kind": f["kind"],
            "title": f["title"], "description": f["description"], "tags": json.loads(f["tags"] or "[]"),
            "url": file_url(f["id"]), "folder_url": folder_url(f["parent_id"]) if f["parent_id"] else "",
            "score": round(scores[rid], 5), "why": why.get(rid, []),
        })
    return out
