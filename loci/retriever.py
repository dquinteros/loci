from __future__ import annotations
import math
from collections import defaultdict
from time import time

from . import config, store, refs
from .embedder import embed


def _apply_file_boost(
    scores: dict[str, float], q_emb, k: int, project: str | None
) -> None:
    file_hits = store.file_index_search(q_emb, k=k, project=project)
    if not file_hits:
        return
    file_chunk_map = store.get_chunk_ids_for_files(
        [fp for fp, _, _ in file_hits], project=project or "",
    )
    for rank, (fp, _, _) in enumerate(file_hits):
        for chunk_id in file_chunk_map.get(fp, []):
            scores[chunk_id] += config.FILE_BOOST / (rank + 60)


def _apply_boosts(
    scores: dict[str, float], mems: list[store.Memory]
) -> None:
    now = time()
    for m in mems:
        if m.id not in scores:
            continue
        scores[m.id] *= config.SOURCE_BOOST.get(m.source, 1.0)
        age_hours = (now - m.created_at) / 3600
        scores[m.id] *= math.exp(-config.RECENCY_DECAY * age_hours)


def hybrid_search(
    query: str,
    k: int = config.TOP_K,
    project: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
) -> list[store.Memory]:
    if project:
        all_projects = refs.resolve_projects(project)
        if len(all_projects) > 1:
            return _hybrid_search_cross_project(
                query, k, project, all_projects, source=source, tags=tags
            )

    q_emb = embed([query])[0]
    vec_hits = store.vector_search(
        q_emb, k=k * 3, project=project, source=source, tags=tags
    )
    fts_hits = store.fts_search(
        query, k=k * 3, project=project, source=source, tags=tags
    )

    scores: dict[str, float] = defaultdict(float)
    for rank, (mem_id, _) in enumerate(vec_hits):
        scores[mem_id] += 1 / (rank + 60)
    for rank, (mem_id, _) in enumerate(fts_hits):
        scores[mem_id] += 1 / (rank + 60)

    _apply_file_boost(scores, q_emb, k, project)

    all_mems = store.get_by_ids(list(scores))
    _apply_boosts(scores, all_mems)

    top_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:k]
    id_set = set(top_ids)
    ordered = [m for mid in top_ids for m in all_mems if m.id == mid]
    return ordered


def _hybrid_search_cross_project(
    query: str,
    k: int,
    current_project: str,
    projects: list[str],
    source: str | None = None,
    tags: list[str] | None = None,
) -> list[store.Memory]:
    q_emb = embed([query])[0]
    vec_hits = store.vector_search(
        q_emb, k=k * 3, projects=projects, source=source, tags=tags
    )
    fts_hits = store.fts_search(
        query, k=k * 3, projects=projects, source=source, tags=tags
    )

    all_ids = list({mid for mid, _ in vec_hits} | {mid for mid, _ in fts_hits})
    all_mems = store.get_by_ids(all_ids)
    id_to_project = {m.id: m.project for m in all_mems}

    scores: dict[str, float] = defaultdict(float)
    for rank, (mem_id, _) in enumerate(vec_hits):
        weight = 1.0 if id_to_project.get(mem_id) == current_project else config.REF_WEIGHT
        scores[mem_id] += weight / (rank + 60)
    for rank, (mem_id, _) in enumerate(fts_hits):
        weight = 1.0 if id_to_project.get(mem_id) == current_project else config.REF_WEIGHT
        scores[mem_id] += weight / (rank + 60)

    _apply_file_boost(scores, q_emb, k, current_project)
    _apply_boosts(scores, all_mems)

    top_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:k]
    ordered = [m for mid in top_ids for m in all_mems if m.id == mid]
    return ordered
