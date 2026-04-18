from __future__ import annotations
import numpy as np
from . import config

_model = None


def embed(texts: list[str]) -> np.ndarray:
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(config.EMBED_MODEL)
    return np.array(list(_model.embed(texts)), dtype=np.float32)
