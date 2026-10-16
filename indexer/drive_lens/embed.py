"""Vectors: a multimodal sentence-transformers model run locally (Apple
GPU, NVIDIA GPU, or CPU). DRIVE_LENS_EMBED_MODEL picks it; the default is
EmbeddingGemma 2. The model must embed images and text into one space (the
image is what gets indexed, the query is words); the vector width comes
from the model.

Images are embedded as pixels; a PDF as its preview plus its text (where the
model takes both at once, else the preview alone). Queries use the model's
"SearchQuery" prompt when it has one. float32 by default; DRIVE_LENS_DTYPE=
bfloat16 halves the weights (~1.5 GB for EmbeddingGemma 2) for small
machines. The search app embeds queries with the ONNX build of the same
model (DRIVE_LENS_QUERY_MODEL), so vectors stay comparable.

On Apple GPUs PyTorch keeps freed blocks cached and that cache grows batch
after batch (an 8 GB M1 ended with 6.3 GB wired and the rest swapping), so
the cache is emptied after every batch."""

from __future__ import annotations

import os

import numpy as np

MODEL_ID = os.environ.get("DRIVE_LENS_EMBED_MODEL", "google/embeddinggemma-2")
DTYPE = os.environ.get("DRIVE_LENS_DTYPE", "float32")


def pick_device() -> str:
    import torch
    want = os.environ.get("DRIVE_LENS_DEVICE")
    if want:
        return want
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Embedder:
    def __init__(self, device: str | None = None):
        self.device = device or pick_device()
        self._model = None

    model_id = MODEL_ID

    @property
    def dims(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def _prompt(self, name: str) -> str | None:
        return name if name in (getattr(self.model, "prompts", None) or {}) else None

    @property
    def label(self) -> str:
        return f"{MODEL_ID} ({self.device}{'' if DTYPE == 'float32' else ', ' + DTYPE})"

    @property
    def model(self):
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(MODEL_ID, device=self.device, model_kwargs={"torch_dtype": getattr(torch, DTYPE)})
        return self._model

    def vectors(self, images: list, texts: list[str], batch_size: int = 8) -> np.ndarray:
        """One vector per file. images[i] alone → the picture; with texts[i] →
        picture and text together (PDFs: preview + their words); images[i]
        None → the text alone (the model's Document prompt is added here, so
        texts must not carry their own "title: … | text: …")."""
        out: list[np.ndarray | None] = [None] * len(images)
        plain = [i for i, (im, t) in enumerate(zip(images, texts)) if im is not None and not t]
        if plain:
            for i, row in zip(plain, self.model.encode([images[i] for i in plain], batch_size=batch_size, normalize_embeddings=True)):
                out[i] = row
        words = [i for i, im in enumerate(images) if im is None]
        if words:
            for i, row in zip(words, self.model.encode([texts[i] for i in words], prompt_name=self._prompt("Document"), normalize_embeddings=True)):
                out[i] = row
        for i, (im, t) in enumerate(zip(images, texts)):
            if im is not None and t:
                try:  # picture and words in one input (EmbeddingGemma 2's interleaved format)
                    out[i] = self.model.encode([{"text": f"<|image|> text: {t}", "image": [im]}], normalize_embeddings=True)[0]
                except Exception:  # a model without mixed inputs: the picture alone
                    out[i] = self.model.encode([im], normalize_embeddings=True)[0]
        self.release()
        return np.stack(out).astype(np.float32)

    def release(self) -> None:
        """Hand the GPU's cached blocks back (Apple GPUs keep growing them otherwise)."""
        if self.device == "mps":
            import torch
            torch.mps.empty_cache()
        elif self.device == "cuda":
            import torch
            torch.cuda.empty_cache()

    def query(self, text: str) -> np.ndarray:
        return self.model.encode(text, prompt_name=self._prompt("SearchQuery"), normalize_embeddings=True).astype(np.float32)
