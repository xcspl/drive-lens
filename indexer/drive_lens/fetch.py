"""Getting something to look at for each file, without keeping the file.

Photos, videos, camera RAW, HEIC and PDFs all have a Drive preview image,
fetched at 1024 px (a few hundred KB instead of the original's megabytes or
gigabytes). PDFs are also downloaded once for their text, then dropped."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from .drive import AnonymousSource, Locked

MODEL_SIDE = 1024
THUMB_SIDE = 256
PDF_TEXT_CHARS = 4000
PDF_MAX_BYTES = 80_000_000


@dataclass
class Prepared:
    image: Image.Image | None   # RGB, ≤ MODEL_SIDE, for the embedder; None: no preview (documents, other)
    jpeg: bytes                 # the same image as JPEG, for the describer
    thumb: bytes                # small JPEG kept in the index for the search app
    text: str = ""              # PDF text, if any
    note: str = ""              # e.g. why the text is missing


def to_rgb(data: bytes, side: int) -> Image.Image:
    with Image.open(io.BytesIO(data)) as im:
        im.seek(0)
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.thumbnail((side, side))
        return im.copy()


def jpeg_bytes(im: Image.Image, side: int | None = None, quality: int = 85) -> bytes:
    if side:
        im = im.copy()
        im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def pdf_text(data: bytes, chars: int = PDF_TEXT_CHARS) -> str:
    import pymupdf
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        out = []
        for page in doc:
            out.append(page.get_text())
            if sum(map(len, out)) >= chars:
                break
    return " ".join(" ".join(out).split())[:chars]


VISUAL = {"image", "video", "pdf"}


def prepare(source: AnonymousSource, file_id: str, kind: str) -> Prepared:
    """Raises Locked when a photo, video or PDF has no preview we may read.
    Documents and other files without a preview get an empty Prepared: they
    are indexed by their name and folder path."""
    try:
        img = to_rgb(source.thumbnail(file_id, MODEL_SIDE), MODEL_SIDE)
    except Locked:
        if kind in VISUAL:
            raise
        return Prepared(image=None, jpeg=b"", thumb=b"", note="no preview")
    p = Prepared(image=img, jpeg=jpeg_bytes(img), thumb=jpeg_bytes(img, THUMB_SIDE, 75))
    if kind == "pdf":
        try:
            p.text = pdf_text(source.download(file_id, PDF_MAX_BYTES))
        except (Locked, IOError) as e:
            p.note = f"text not read: {e}"
        except Exception as e:  # a broken PDF still has its preview
            p.note = f"text not read: {type(e).__name__}"
    return p
