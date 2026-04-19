from __future__ import annotations
from collections import defaultdict

from . import config, store, refs
from .embedder import embed


def hybrid_search(
    query: str, k: int = config.TOP_K, project: str | None = None
) -> list[store.Memory]:
    if project:
        all_projects = refs.resolve_projects(project)
        if len(all_projects) > 1:
            return _hybrid_search_cross_project(query, k, project, all_projects)

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


def _hybrid_search_cross_project(
    query: str, k: int, current_project: str, projects: list[str]
) -> list[store.Memory]:
    q_emb = embed([query])[0]
    vec_hits = store.vector_search(q_emb, k=k * 3, projects=projects)
    fts_hits = store.fts_search(query, k=k * 3, projects=projects)

    all_ids = list({mid for mid, _ in vec_hits} | {mid for mid, _ in fts_hits})
    id_to_project = {
        m.id: m.project for m in store.get_by_ids(all_ids)
    }

    scores: dict[str, float] = defaultdict(float)
    for rank, (mem_id, _) in enumerate(vec_hits):
        weight = 1.0 if id_to_project.get(mem_id) == current_project else config.REF_WEIGHT
        scores[mem_id] += weight / (rank + 60)
    for rank, (mem_id, _) in enumerate(fts_hits):
        weight = 1.0 if id_to_project.get(mem_id) == current_project else config.REF_WEIGHT
        scores[mem_id] += weight / (rank + 60)

    top_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:k]
    return store.get_by_ids(top_ids)
