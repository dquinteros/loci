from __future__ import annotations
from pathlib import Path

from .. import store
from ..chunker import chunk


def ingest(path: str | Path, project: str = "") -> int:
    from pypdf import PdfReader

    path = Path(path)
    reader = PdfReader(str(path))
    text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    chunks_text = chunk(text)
    chunks_input = [
        store.ChunkInput(
            content=c, tags=["pdf"], project=project,
            source="file", source_ref=str(path), chunk_idx=idx,
        )
        for idx, c in enumerate(chunks_text)
    ]
    results = store.insert_batch(chunks_input)
    return sum(1 for r in results if r is not None)
