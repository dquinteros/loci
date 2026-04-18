from __future__ import annotations
from pathlib import Path

from .. import store
from ..chunker import chunk


def ingest(path: str | Path, project: str = "") -> int:
    import docx

    path = Path(path)
    doc = docx.Document(str(path))
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    chunks = chunk(text)
    count = 0
    for idx, c in enumerate(chunks):
        if store.insert(c, tags=["docx"], project=project, source="file",
                        source_ref=str(path), chunk_idx=idx):
            count += 1
    return count
