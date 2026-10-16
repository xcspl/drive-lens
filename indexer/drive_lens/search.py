"""Hybrid search over an index.

Several ranked lists, fused with weighted Reciprocal Rank Fusion
(score = Σ weight / (RRF_K + rank)):

- meaning: vector similarity (sqlite-vec), above a similarity floor;
- all:     files containing every word (FTS5 AND) — the classic "coordination"
           reward for matching more of the query;
- near:    the words close together (FTS5 NEAR) — "thai rangers training";
- any:     any of the words (FTS5 OR), weighted low — partial matches, so a
           query never comes back empty just because one word is missing.

A file found by several lists rises on its own. The search box also takes
`"exact phrase"` (must appear) and `-word` (must not appear); both apply to
every list, meaning included. The app (app/electron/search.js) implements the
same rules.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import store
from .drive import file_url, folder_url

RRF_K = 60
POOL = 200
# Nearest vectors always exist, even for a query about nothing in the index
# (EmbeddingGemma 2 on the first 70 files: unrelated queries ~0.55-0.59, real
# matches mostly 0.6-0.76, a few weaker ones just under 0.6);
# below this cosine similarity a vector "match" earns no rank, so a file
# found by its words is not outranked by an unrelated picture.
MIN_SIM = float(os.environ.get("DRIVE_LENS_MIN_SIM", "0.5"))
LIST_WEIGHTS = {"meaning": 1.0, "all": 1.0, "near": 0.6, "any": 0.35}
NEAR_DISTANCE = 6
STOP = set("a an and are as at be by for from has have in is it of on or the to was were with this that these those photo photos image images picture pictures file files show shows".split())
# bm25 weights, in files_fts column order: name, path, title, description, details, tags, text_in_image
WEIGHTS = (1.5, 2.0, 1.5, 1.0, 0.5, 1.5, 1.0)
_WORD = re.compile(r"\w+")


@dataclass
class Query:
    words: list[str] = field(default_factory=list)     # free words (stop words dropped)
    phrases: list[str] = field(default_factory=list)   # "quoted": must appear, in order
    exclude: list[str] = field(default_factory=list)   # -word: must not appear

    @property
    def text(self) -> str:
        """What the meaning list embeds: the words and phrases, not the exclusions."""
        return " ".join(self.phrases + self.words)


def parse(q: str) -> Query:
    out = Query()
    out.phrases = [p for p in (" ".join(_WORD.findall(x.lower())) for x in re.findall(r'"([^"]+)"', q)) if p]
    rest = re.sub(r'"[^"]*"?', " ", q)
    out.exclude = [w.lower() for w in re.findall(r"(?:^|\s)-(\w+)", rest)]
    rest = re.sub(r"(?:^|\s)-\w+", " ", rest)
    out.words = [w for w in _WORD.findall(rest.lower()) if w not in STOP and len(w) > 1]
    return out


def _term(w: str) -> str:
    return f'"{w}"*' if len(w) >= 4 else f'"{w}"'


def fts_queries(q: Query) -> dict[str, str]:
    """The FTS5 query for each keyword list (absent when it does not apply)."""
    must = " AND ".join(f'"{p}"' for p in q.phrases)
    ban = "".join(f" NOT {_term(w)}" for w in q.exclude)

    def wrap(core: str) -> str:
        return " AND ".join(x for x in (must, f"({core})") if x) + ban

    out: dict[str, str] = {}
    if q.words:
        out["all"] = wrap(" AND ".join(_term(w) for w in q.words))
        if len(q.words) >= 2:
            out["near"] = wrap(f"NEAR({' '.join(_term(w) for w in q.words)}, {NEAR_DISTANCE})")
            out["any"] = wrap(" OR ".join(_term(w) for w in q.words))
    elif must:
        out["all"] = must + ban
    return out


def fts_query(q: str) -> str:
    """The plain any-word query (one FTS string, for callers that want just that)."""
    return " OR ".join(_term(w) for w in parse(q).words)


def _matching(conn, fts: str) -> set[int]:
    return {r[0] for r in conn.execute("SELECT rowid FROM files_fts WHERE files_fts MATCH ?", (fts,))}


def search(conn, q: str, *, embedder=None, k: int = 20) -> list[dict]:
    pq = parse(q)
    scores: dict[int, float] = {}
    why: dict[int, list[str]] = {}

    def add(rowid: int, rank: int, name: str, label: str) -> None:
        scores[rowid] = scores.get(rowid, 0.0) + LIST_WEIGHTS[name] / (RRF_K + rank)
        why.setdefault(rowid, []).append(label)

    # Phrases and exclusions bind the meaning list too.
    must = _matching(conn, " AND ".join(f'"{p}"' for p in pq.phrases)) if pq.phrases else None
    banned = _matching(conn, " OR ".join(_term(w) for w in pq.exclude)) if pq.exclude else set()

    if embedder is not None and pq.text and store.has_vec(conn) and conn.execute("SELECT 1 FROM files_vec LIMIT 1").fetchone():
        qv = embedder.query(pq.text)
        hits = conn.execute("SELECT rowid, distance FROM files_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                            (store.pack(qv), POOL)).fetchall()
        keep = [h for h in hits if 1 - h[1] >= MIN_SIM and h[0] not in banned and (must is None or h[0] in must)]
        for rank, (rid, dist) in enumerate(keep):
            add(rid, rank, "meaning", f"meaning #{rank + 1} ({1 - dist:.2f})")

    bm25 = f"bm25(files_fts, {', '.join(map(str, WEIGHTS))})"
    for name, fts in fts_queries(pq).items():
        rows = conn.execute(f"SELECT rowid FROM files_fts WHERE files_fts MATCH ? ORDER BY {bm25} LIMIT ?", (fts, POOL)).fetchall()
        for rank, (rid,) in enumerate(rows):
            add(rid, rank, name, f"{name} #{rank + 1}")

    out = []
    for rid in sorted(scores, key=scores.get, reverse=True)[:k]:
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
