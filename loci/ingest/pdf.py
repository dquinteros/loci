from __future__ import annotations
from pathlib import Path

from .. import store
from ..chunker import chunk


def ingest(path: str | Path, project: str = "") -> int:
    from pypdf import PdfReader

    path = Path(path)
    reader = PdfReader(str(path))
    text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    chunks = chunk(text)
    count = 0
    for idx, c in enumerate(chunks):
        if store.insert(c, tags=["pdf"], project=project, source="file",
                        source_ref=str(path), chunk_idx=idx):
            count += 1
    return count
