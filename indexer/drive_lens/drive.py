"""Google Drive access through a share link.

Two sources behind one interface:

- `AnonymousSource` (no key): the public "embedded folder view" page for
  listings, `drive.google.com/thumbnail` for preview images (photos, videos,
  RAW, HEIC and PDFs alike), and the public download URL for full files.
  Works for anything shared as "anyone with the link"; restricted folders
  answer 401 and are recorded as locked.
- `ApiKeySource` (GOOGLE_API_KEY): the official Drive API v3 on the same
  link-shared files — stable, adds sizes, checksums and exact dates.
"""

from __future__ import annotations

import html
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterator

UA = "Mozilla/5.0 (compatible; drive-lens/0.1; +https://github.com/xcspl/drive-lens)"
FOLDER_MIME = "application/vnd.google-apps.folder"


class Locked(Exception):
    """The folder or file is not shared with the link (or does not exist)."""


@dataclass
class Entry:
    id: str
    name: str
    mime: str = ""
    is_folder: bool = False
    size: int | None = None
    modified: str = ""
    md5: str = ""


@dataclass
class Item:
    """A file found by the walk, with its place in the tree."""
    entry: Entry
    path: str  # "Folder/Sub/name.jpg", relative to the shared root
    parent_id: str


def kind_of(mime: str, name: str) -> str:
    m, ext = mime.lower(), name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if m.startswith("image/") or ext in {"jpg", "jpeg", "png", "heic", "heif", "webp", "gif", "tif", "tiff", "nef", "cr2", "arw", "dng"}:
        return "image"
    if m.startswith("video/") or ext in {"mp4", "mov", "m4v", "avi", "mkv", "webm", "mts", "wmv", "mpg", "mpeg", "3gp", "flv", "vob", "m2ts"}:
        return "video"
    if m == "application/pdf" or ext == "pdf":
        return "pdf"
    if m.startswith("application/vnd.google-apps.") or ext in {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "rtf", "odt"}:
        return "document"
    return "other"


def file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _get(url: str, *, timeout: float = 60, retries: int = 3, accept_html: bool = True) -> tuple[bytes, str]:
    """GET with retries on 429/5xx/network errors. Returns (body, content-type)."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise Locked(f"HTTP {e.code}") from None
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if attempt < retries:
            time.sleep(min(30.0, 2 * 2 ** attempt) * (0.75 + random.random() / 2))
    raise IOError(f"GET failed: {last}")


def parse_embedded_view(page: str) -> list[Entry]:
    """Entries of Drive's embedded folder view: one `flip-entry` block each,
    with the link, the type icon (`…/type/image/png`), title and date.

    A shortcut's block id is the shortcut itself; its link points at the
    target, which is what we want (listing the shortcut id returns an empty
    page, not an error). So the id is taken from the link."""
    out = []
    for block in page.split('<div class="flip-entry" id="entry-')[1:]:
        own = re.match(r"[\w-]+", block)
        href = re.search(r'<a href="([^"]+)"', block)
        name = re.search(r'<div class="flip-entry-title">(.*?)</div>', block, re.S)
        if not (own and href and name):
            continue
        target = re.search(r"/(?:folders|d)/([\w-]+)", href.group(1))
        fid = target.group(1) if target else own.group(0)
        mime = re.search(r'/type/([\w.+-]+/[\w.+-]+)"', block)
        modified = re.search(r'<div class="flip-entry-last-modified"><div>(.*?)</div>', block, re.S)
        is_folder = "/folders/" in href.group(1)
        out.append(Entry(id=fid, name=html.unescape(name.group(1)).strip(),
                         mime=FOLDER_MIME if is_folder else (mime.group(1) if mime else ""),
                         is_folder=is_folder, modified=html.unescape(modified.group(1)).strip() if modified else ""))
    return out


class AnonymousSource:
    name = "anonymous"

    def list_folder(self, folder_id: str) -> list[Entry]:
        body, _ = _get(f"https://drive.google.com/embeddedfolderview?id={folder_id}")
        return parse_embedded_view(body.decode("utf-8", "replace"))

    def thumbnail(self, file_id: str, side: int = 1024) -> bytes:
        body, ctype = _get(f"https://drive.google.com/thumbnail?id={file_id}&sz=w{side}")
        if not ctype.startswith("image/"):
            raise Locked("no preview image")
        return body

    def download(self, file_id: str, max_bytes: int = 200_000_000) -> bytes:
        body, ctype = _get(f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t", timeout=300)
        if ctype.startswith("text/html"):  # Drive's "can't download" page, not the file
            raise Locked("not publicly downloadable")
        if len(body) > max_bytes:
            raise IOError(f"file larger than {max_bytes} bytes")
        return body


class ApiKeySource(AnonymousSource):
    """Drive API v3 with an API key. Previews and downloads as the anonymous source."""
    name = "api-key"
    FIELDS = "nextPageToken, files(id, name, mimeType, size, md5Checksum, modifiedTime)"

    def __init__(self, key: str):
        self.key = key

    def list_folder(self, folder_id: str) -> list[Entry]:
        out, token = [], ""
        while True:
            q = urllib.parse.urlencode({
                "q": f"'{folder_id}' in parents and trashed = false", "fields": self.FIELDS, "pageSize": 1000,
                "key": self.key, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", **({"pageToken": token} if token else {}),
            })
            body, _ = _get(f"https://www.googleapis.com/drive/v3/files?{q}")
            d = json.loads(body)
            for f in d.get("files", []):
                out.append(Entry(id=f["id"], name=f["name"], mime=f.get("mimeType", ""), is_folder=f.get("mimeType") == FOLDER_MIME,
                                 size=int(f["size"]) if f.get("size") else None, modified=f.get("modifiedTime", ""), md5=f.get("md5Checksum", "")))
            token = d.get("nextPageToken", "")
            if not token:
                return out


def source_for(google_api_key: str) -> AnonymousSource:
    return ApiKeySource(google_api_key) if google_api_key else AnonymousSource()


@dataclass
class WalkReport:
    folders: int = 0
    files: int = 0
    locked: list[tuple[str, str, str]] = field(default_factory=list)  # (id, path, reason)


def walk(source: AnonymousSource, root_id: str, *, pause: float = 0.3,
         on_folder: Callable[[str, str, str | None], None] | None = None,
         report: WalkReport | None = None) -> Iterator[Item]:
    """Breadth-first over the shared tree, yielding every file with its path.
    `on_folder(id, path, parent_id)` sees each readable folder; locked ones go
    in `report.locked`."""
    report = report if report is not None else WalkReport()
    queue: deque[tuple[str, str, str | None]] = deque([(root_id, "", None)])
    seen = {root_id}
    while queue:
        fid, path, parent = queue.popleft()
        try:
            entries = source.list_folder(fid)
        except Locked as e:
            report.locked.append((fid, path, str(e)))
            continue
        report.folders += 1
        if on_folder:
            on_folder(fid, path, parent)
        for e in entries:
            p = f"{path}/{e.name}" if path else e.name
            if e.is_folder:
                if e.id not in seen:
                    seen.add(e.id)
                    queue.append((e.id, p, fid))
            else:
                report.files += 1
                yield Item(entry=e, path=p, parent_id=fid)
        if pause:
            time.sleep(pause)
