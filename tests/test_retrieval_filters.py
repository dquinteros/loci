"""Tests for source/tag filtering, source boost, and recency decay."""
from __future__ import annotations

import os
import threading

import pytest

os.environ["LOCI_DB_PATH"] = ""


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_memories.db"
    monkeypatch.setattr("loci.config.DB_PATH", db_path)
    import loci.store as _store
    _store.close()
    _store._local = threading.local()
    _store.init_db()
    yield
    _store.close()


from loci import store, retriever, config
from loci.store import insert


def _insert(content, source="manual", tags=None, project="/test-proj", created_at=None):
    """Helper: insert and optionally backdate."""
    mem_id = insert(content, tags=tags or [], project=project, source=source)
    if created_at is not None and mem_id:
        con = store._connect()
        con.execute("UPDATE memories SET created_at=? WHERE id=?", (created_at, mem_id))
        con.commit()
    return mem_id


def test_vector_search_filters_by_source():
    _insert("Python uses indentation for blocks", source="code")
    _insert("Always run tests before merging", source="manual")

    from loci.embedder import embed
    q_emb = embed(["coding best practices"])[0]

    manual_hits = store.vector_search(q_emb, k=5, project="/test-proj", source="manual")
    code_hits = store.vector_search(q_emb, k=5, project="/test-proj", source="code")

    manual_ids = {mid for mid, _ in manual_hits}
    code_ids = {mid for mid, _ in code_hits}
    assert manual_ids.isdisjoint(code_ids)


def test_vector_search_filters_by_tags():
    _insert("Session: discussed auth refactor", source="session", tags=["session"])
    _insert("Architecture: use repository pattern", source="manual", tags=["architecture"])

    from loci.embedder import embed
    q_emb = embed(["project patterns"])[0]

    session_hits = store.vector_search(q_emb, k=5, project="/test-proj", tags=["session"])
    arch_hits = store.vector_search(q_emb, k=5, project="/test-proj", tags=["architecture"])

    session_ids = {mid for mid, _ in session_hits}
    arch_ids = {mid for mid, _ in arch_hits}
    assert session_ids.isdisjoint(arch_ids)


def test_fts_search_filters_by_source():
    _insert("SQLite database connection pooling", source="code")
    _insert("SQLite is our primary data store", source="manual")

    code_hits = store.fts_search("SQLite", k=5, project="/test-proj", source="code")
    manual_hits = store.fts_search("SQLite", k=5, project="/test-proj", source="manual")

    code_ids = {mid for mid, _ in code_hits}
    manual_ids = {mid for mid, _ in manual_hits}
    assert len(code_ids) == 1
    assert len(manual_ids) == 1
    assert code_ids.isdisjoint(manual_ids)


def test_hybrid_search_threads_source_filter():
    _insert("Vector search uses cosine similarity", source="code")
    _insert("We decided to use vector search for retrieval", source="session")

    results = retriever.hybrid_search(
        "vector search", k=5, project="/test-proj", source="session"
    )
    assert all(m.source == "session" for m in results)


def test_source_boost_manual_outranks_code():
    _insert("Use repository pattern for data access", source="manual")
    _insert("Use repository pattern for data access layer", source="code")

    results = retriever.hybrid_search(
        "repository pattern data access", k=2, project="/test-proj"
    )
    assert len(results) == 2
    assert results[0].source == "manual"


def test_recency_boost_newer_outranks_older():
    from time import time
    now = time()
    old_time = now - (30 * 24 * 3600)  # 30 days ago

    _insert("Recent deployment fix for auth service", source="session", created_at=now)
    _insert("Old deployment fix for auth service", source="session", created_at=old_time)

    results = retriever.hybrid_search(
        "deployment fix auth", k=2, project="/test-proj"
    )
    assert len(results) == 2
    assert "Recent" in results[0].content


def test_multi_query_session_start_returns_mixed_sources():
    _insert("Session: migrated to new API", source="session", tags=["session"])
    _insert("Architecture: microservices pattern", source="manual", tags=["architecture"])
    _insert("def main(): app.run()", source="code", tags=["code"])

    categories = [
        {"query": "session summary decisions progress", "k": 3, "source": "session"},
        {"query": "project architecture conventions facts", "k": 3, "source": "manual"},
        {"query": "important functions main components", "k": 3, "source": "code"},
    ]

    seen_ids: set[str] = set()
    memories: list[store.Memory] = []
    for cat in categories:
        hits = retriever.hybrid_search(
            cat["query"], k=cat["k"], project="/test-proj",
            source=cat["source"],
        )
        for m in hits:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                memories.append(m)

    sources_found = {m.source for m in memories}
    assert "session" in sources_found
    assert "manual" in sources_found
    assert "code" in sources_found
