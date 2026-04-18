from __future__ import annotations
from collections import defaultdict

from . import config, store
from .embedder import embed


def hybrid_search(
    query: str, k: int = config.TOP_K, project: str | None = None
) -> list[store.Memory]:
    q_emb = embed([query])[0]
    vec_hits = store.vector_search(q_emb, k=k * 3, project=project)
    fts_hits = store.fts_search(query, k=k * 3, project=project)

    scores: dict[str, float] = defaultdict(float)
    for rank, (mem_id, _) in enumerate(vec_hits):
        scores[mem_id] += 1 / (rank + 60)
    for rank, (mem_id, _) in enumerate(fts_hits):
        scores[mem_id] += 1 / (rank + 60)

    top_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:k]
    return store.get_by_ids(top_ids)
