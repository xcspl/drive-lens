"""The index: one SQLite file with the Drive listing, the descriptions,
small thumbnails, a keyword index (FTS5) and the vectors (sqlite-vec).

The search app reads the same file, so the schema is the contract:
`files` rows are keyed by `rowid`, which is also the rowid in `files_fts`,
`files_vec` and `thumbs`.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec

SCHEMA_VERSION = 1
DIMS = 768

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY, path TEXT NOT NULL, parent_id TEXT,
  locked INTEGER NOT NULL DEFAULT 0, error TEXT, seen_at TEXT
);
CREATE TABLE IF NOT EXISTS files (
  rowid INTEGER PRIMARY KEY,
  id TEXT NOT NULL UNIQUE,          -- Drive file id
  name TEXT NOT NULL, mime TEXT, kind TEXT NOT NULL,
  size INTEGER, md5 TEXT, modified TEXT,
  path TEXT NOT NULL,               -- "Folder/Sub/name.jpg" from the shared root
  parent_id TEXT,
  status TEXT NOT NULL DEFAULT 'listed',   -- listed | done | skipped | error
  error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  title TEXT, description TEXT, details TEXT, category TEXT, tags TEXT,
  text_in_image TEXT, setting TEXT, people_count INTEGER, sensitive INTEGER,
  described_by TEXT, embedded_by TEXT,
  listed_at TEXT, updated_at TEXT, seen_at TEXT
);
CREATE INDEX IF NOT EXISTS files_status ON files (status, kind);
CREATE TABLE IF NOT EXISTS thumbs (rowid INTEGER PRIMARY KEY, jpeg BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY, file_rowid INTEGER, model TEXT, effort TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, reasoning_tokens INTEGER, cached_tokens INTEGER,
  seconds REAL, ok INTEGER, error TEXT, at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
  name, path, title, description, details, tags, text_in_image,
  tokenize = 'porter unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS files_vec USING vec0(embedding float[{DIMS}] distance_metric=cosine);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{path}?mode=ro" if readonly else f"file:{path}"
    conn = sqlite3.connect(uri, uri=True, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    if not readonly:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        if "cached_tokens" not in {r[1] for r in conn.execute("PRAGMA table_info(usage)")}:  # added 2026-10-16
            conn.execute("ALTER TABLE usage ADD COLUMN cached_tokens INTEGER")
        conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    return conn


def set_meta(conn: sqlite3.Connection, **kv: object) -> None:
    conn.executemany("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     [(k, v if isinstance(v, str) else json.dumps(v)) for k, v in kv.items()])


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def pack(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def fts_text(name: str) -> str:
    """File names like Elephant_Campaign_2026.jpg searchable by their words."""
    return name.replace("_", " ").replace(".", " ")


def refresh_fts(conn: sqlite3.Connection, rowid: int) -> None:
    r = conn.execute("SELECT name, path, title, description, details, tags, text_in_image FROM files WHERE rowid = ?", (rowid,)).fetchone()
    conn.execute("DELETE FROM files_fts WHERE rowid = ?", (rowid,))
    if r is None:
        return
    tags = " ".join(t.replace("-", " ") for t in json.loads(r["tags"] or "[]"))
    conn.execute("INSERT INTO files_fts (rowid, name, path, title, description, details, tags, text_in_image) VALUES (?,?,?,?,?,?,?,?)",
                 (rowid, fts_text(r["name"]), r["path"].replace("_", " "), r["title"] or "", r["description"] or "",
                  r["details"] or "", tags, r["text_in_image"] or ""))


def upsert_folder(conn: sqlite3.Connection, fid: str, path: str, parent: str | None, stamp: str, *, locked: str | None = None) -> None:
    conn.execute(
        "INSERT INTO folders (id, path, parent_id, locked, error, seen_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET path=excluded.path, parent_id=excluded.parent_id, locked=excluded.locked, error=excluded.error, seen_at=excluded.seen_at",
        (fid, path, parent, 1 if locked else 0, locked, stamp))


def upsert_file(conn: sqlite3.Connection, *, id: str, name: str, mime: str, kind: str, size, md5: str, modified: str,
                path: str, parent_id: str, stamp: str) -> str:
    """Record a listed file. Returns 'new', 'changed' (content changed: redo),
    'moved' (path or name only) or 'same'."""
    old = conn.execute("SELECT rowid, name, path, md5, modified, size FROM files WHERE id = ?", (id,)).fetchone()
    if old is None:
        cur = conn.execute(
            "INSERT INTO files (id, name, mime, kind, size, md5, modified, path, parent_id, listed_at, updated_at, seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (id, name, mime, kind, size, md5, modified, path, parent_id, stamp, stamp, stamp))
        refresh_fts(conn, cur.lastrowid)
        return "new"
    content_changed = (md5 and old["md5"] and md5 != old["md5"]) or (size and old["size"] and size != old["size"])
    moved = old["path"] != path or old["name"] != name
    conn.execute("UPDATE files SET name=?, mime=?, kind=?, size=COALESCE(?, size), md5=COALESCE(NULLIF(?, ''), md5), modified=?, path=?, parent_id=?, seen_at=? WHERE rowid=?",
                 (name, mime, kind, size, md5, modified, path, parent_id, stamp, old["rowid"]))
    if content_changed:
        conn.execute("UPDATE files SET status='listed', error=NULL, attempts=0, updated_at=? WHERE rowid=?", (stamp, old["rowid"]))
        conn.execute("DELETE FROM files_vec WHERE rowid = ?", (old["rowid"],))
    if content_changed or moved:
        refresh_fts(conn, old["rowid"])
    return "changed" if content_changed else "moved" if moved else "same"


# A sync never removes more than this share of the index (or MASS_REMOVAL_MIN
# files, whichever is larger) in one go: a broken listing must not wipe it.
MASS_REMOVAL_SHARE = 0.2
MASS_REMOVAL_MIN = 50


def keep_under(conn: sqlite3.Connection, folder_path: str, stamp: str) -> int:
    """Mark files and folders under `folder_path` as seen: a folder that was
    readable before and is locked now (sharing changed, or Google refused for
    a moment) keeps its files and their descriptions."""
    if not folder_path:
        return 0
    like = folder_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    n = conn.execute("UPDATE files SET seen_at = ? WHERE path LIKE ? ESCAPE '\\'", (stamp, like)).rowcount
    conn.execute("UPDATE folders SET seen_at = ? WHERE path LIKE ? ESCAPE '\\'", (stamp, like))
    return n


def unseen(conn: sqlite3.Connection, stamp: str) -> list[int]:
    return [r[0] for r in conn.execute("SELECT rowid FROM files WHERE seen_at IS NOT ?", (stamp,))]


def remove_unseen(conn: sqlite3.Connection, stamp: str, *, force: bool = False) -> tuple[int, str]:
    """After a complete walk: forget files and folders no longer in the shared
    tree. Returns (removed, note); refuses a mass removal unless forced."""
    gone = unseen(conn, stamp)
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    limit = max(MASS_REMOVAL_MIN, int(total * MASS_REMOVAL_SHARE))
    if len(gone) > limit and not force:
        return 0, (f"{len(gone)} of {total} files were not seen in this listing — more than the {limit} a sync may "
                   f"remove at once, so nothing was removed. If they really left the Drive, run `drive-lens list --allow-mass-removal`.")
    for rid in gone:
        for t in ("files_fts", "files_vec", "thumbs"):
            conn.execute(f"DELETE FROM {t} WHERE rowid = ?", (rid,))
        conn.execute("DELETE FROM files WHERE rowid = ?", (rid,))
    conn.execute("DELETE FROM folders WHERE seen_at IS NOT ?", (stamp,))
    return len(gone), ""


def save_done(conn: sqlite3.Connection, rowid: int, *, analysis: dict | None, vector, thumb: bytes | None,
              described_by: str, embedded_by: str) -> None:
    a = analysis or {}
    conn.execute(
        "UPDATE files SET status='done', error=NULL, title=?, description=?, details=?, category=?, tags=?, text_in_image=?, setting=?, "
        "people_count=?, sensitive=?, described_by=?, embedded_by=?, updated_at=? WHERE rowid=?",
        (a.get("title"), a.get("description"), a.get("details"), a.get("category"), json.dumps(a.get("tags") or []),
         a.get("text_in_image"), a.get("setting"), a.get("people_count"), 1 if a.get("sensitive") else 0 if a else None,
         described_by or None, embedded_by or None, now(), rowid))
    conn.execute("DELETE FROM files_vec WHERE rowid = ?", (rowid,))
    if vector is not None:
        conn.execute("INSERT INTO files_vec (rowid, embedding) VALUES (?, ?)", (rowid, pack(vector)))
    if thumb:
        conn.execute("INSERT INTO thumbs (rowid, jpeg) VALUES (?, ?) ON CONFLICT(rowid) DO UPDATE SET jpeg = excluded.jpeg", (rowid, thumb))
    refresh_fts(conn, rowid)


def save_failure(conn: sqlite3.Connection, rowid: int, error: str, *, skipped: bool = False) -> None:
    conn.execute("UPDATE files SET status=?, error=?, attempts=attempts+1, updated_at=? WHERE rowid=?",
                 ("skipped" if skipped else "error", error[:500], now(), rowid))


def log_usage(conn: sqlite3.Connection, rowid: int, model: str, effort: str, usage: dict, seconds: float, ok: bool, error: str = "") -> None:
    details = usage.get("completion_tokens_details") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    conn.execute("INSERT INTO usage (file_rowid, model, effort, prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens, seconds, ok, error, at) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (rowid, model, effort, usage.get("prompt_tokens"), usage.get("completion_tokens"), details.get("reasoning_tokens"), cached,
                  round(seconds, 2), 1 if ok else 0, error[:300] or None, now()))


def todo(conn: sqlite3.Connection, *, kinds: list[str], limit: int | None, retry_errors: bool, sample: int | None = None,
         retry_skipped: bool = False) -> list[sqlite3.Row]:
    """Files still to process. `sample` picks a fixed pseudo-random spread
    across the tree instead of listing order. Skipped files (no preview) come
    back only with `retry_skipped`, after a fallback was added for them."""
    statuses = ("listed",) + (("error",) if retry_errors else ()) + (("skipped",) if retry_skipped else ())
    q = (f"SELECT rowid, * FROM files WHERE status IN ({','.join('?' * len(statuses))}) AND kind IN ({','.join('?' * len(kinds))}) "
         f"AND (attempts < 3 OR status = 'skipped') ORDER BY {'(rowid * 2654435761) % 4294967296' if sample else 'rowid'}")
    rows = conn.execute(q, (*statuses, *kinds)).fetchall()
    n = sample or limit
    return rows[:n] if n else rows


def stats(conn: sqlite3.Connection) -> dict:
    by = {f"{r['kind']}:{r['status']}": r["n"] for r in conn.execute("SELECT kind, status, COUNT(*) n FROM files GROUP BY kind, status")}
    u = conn.execute("SELECT COUNT(*) calls, SUM(ok) ok, SUM(prompt_tokens) pin, SUM(completion_tokens) pout, SUM(reasoning_tokens) preason, "
                     "SUM(cached_tokens) pcached, AVG(NULLIF(seconds, 0)) secs FROM usage").fetchone()
    return {
        "files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "folders": conn.execute("SELECT COUNT(*) FROM folders WHERE locked = 0").fetchone()[0],
        "locked_folders": [dict(r) for r in conn.execute("SELECT id, path, error FROM folders WHERE locked = 1 ORDER BY path")],
        "by_kind_status": by,
        "vectors": conn.execute("SELECT COUNT(*) FROM files_vec").fetchone()[0],
        "usage": dict(u) if u else {},
        "meta": get_meta(conn),
    }


def rebuild_fts(conn: sqlite3.Connection) -> int:
    """Recreate the keyword index from `files` (after a tokenizer change)."""
    conn.execute("DROP TABLE IF EXISTS files_fts")
    conn.executescript(SCHEMA)
    rows = [r[0] for r in conn.execute("SELECT rowid FROM files")]
    for rid in rows:
        refresh_fts(conn, rid)
    conn.commit()
    return len(rows)
