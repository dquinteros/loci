from __future__ import annotations
from pathlib import Path

from .. import store
from ..chunker import chunk


def ingest(path: str | Path, project: str = "") -> int:
    import docx

    path = Path(path)
    doc = docx.Document(str(path))
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    chunks_text = chunk(text)
    chunks_input = [
        store.ChunkInput(
            content=c, tags=["docx"], project=project,
            source="file", source_ref=str(path), chunk_idx=idx,
        )
        for idx, c in enumerate(chunks_text)
    ]
    results = store.insert_batch(chunks_input)
    return sum(1 for r in results if r is not None)
