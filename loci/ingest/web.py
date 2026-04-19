from __future__ import annotations

from .. import store
from ..chunker import chunk


def ingest(url: str, project: str = "") -> int:
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Could not fetch {url}")
    text = trafilatura.extract(downloaded)
    if not text:
        raise ValueError(f"Could not extract text from {url}")
    chunks_text = chunk(text)
    chunks_input = [
        store.ChunkInput(
            content=c, tags=["web"], project=project,
            source="web", source_ref=url, chunk_idx=idx,
        )
        for idx, c in enumerate(chunks_text)
    ]
    results = store.insert_batch(chunks_input)
    return sum(1 for r in results if r is not None)
