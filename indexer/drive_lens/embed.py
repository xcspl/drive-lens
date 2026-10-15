"""Vectors: EmbeddingGemma 2, run locally (Apple GPU, NVIDIA GPU, or CPU).

Images are embedded as pixels; a PDF as its preview plus its text. Queries
use the model's "SearchQuery" prompt. float32 throughout — the model card
warns against fp16. The search app uses the ONNX build of the same model,
so vectors stay comparable."""

from __future__ import annotations

import os

import numpy as np

MODEL_ID = os.environ.get("DRIVE_LENS_EMBED_MODEL", "google/embeddinggemma-2")


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

    @property
    def label(self) -> str:
        return f"{MODEL_ID} ({self.device})"

    @property
    def model(self):
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(MODEL_ID, device=self.device, model_kwargs={"torch_dtype": torch.float32})
        return self._model

    def vectors(self, images: list, texts: list[str], batch_size: int = 8) -> np.ndarray:
        """One vector per file. images[i] alone → the picture; with texts[i] →
        picture and text together (PDFs: preview + their words); images[i]
        None → the text alone, as a document (files Drive has no preview for:
        their name and folder path)."""
        out: list[np.ndarray | None] = [None] * len(images)
        plain = [i for i, (im, t) in enumerate(zip(images, texts)) if im is not None and not t]
        if plain:
            for i, row in zip(plain, self.model.encode([images[i] for i in plain], batch_size=batch_size, normalize_embeddings=True)):
                out[i] = row
        words = [i for i, im in enumerate(images) if im is None]
        if words:
            for i, row in zip(words, self.model.encode([texts[i] for i in words], prompt_name="Document", normalize_embeddings=True)):
                out[i] = row
        for i, (im, t) in enumerate(zip(images, texts)):
            if im is not None and t:
                out[i] = self.model.encode([{"text": f"<|image|> text: {t}", "image": [im]}], normalize_embeddings=True)[0]
        return np.stack(out).astype(np.float32)

    def query(self, text: str) -> np.ndarray:
        return self.model.encode(text, prompt_name="SearchQuery", normalize_embeddings=True).astype(np.float32)
