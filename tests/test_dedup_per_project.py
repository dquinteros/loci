"""Tests for per-project deduplication in store.py."""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ["LOCI_DB_PATH"] = ""  # overridden per-test in fixture


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_memories.db"
    monkeypatch.setattr("loci.config.DB_PATH", db_path)
    import loci.store as _store
    _store.close()
    _store._local = __import__("threading").local()
    _store.init_db()
    yield
    _store.close()


from loci.store import insert, insert_batch, ChunkInput, list_memories


def test_insert_same_content_different_projects_both_stored():
    content = "export default function App() { return <div>Hello</div>; }"
    id_a = insert(content, tags=["code"], project="/project-a", source="code")
    id_b = insert(content, tags=["code"], project="/project-b", source="code")
    assert id_a is not None
    assert id_b is not None


def test_insert_same_content_same_project_deduped():
    content = "export default function App() { return <div>Hello</div>; }"
    id_a = insert(content, tags=["code"], project="/project-a", source="code")
    id_dup = insert(content, tags=["code"], project="/project-a", source="code")
    assert id_a is not None
    assert id_dup is None


def test_insert_batch_same_content_different_projects():
    content = "const handler = async (req, res) => { res.json({ ok: true }); };"
    chunks = [
        ChunkInput(content=content, tags=["code"], project="/proj-x", source="code", source_ref="a.js", chunk_idx=0),
        ChunkInput(content=content, tags=["code"], project="/proj-y", source="code", source_ref="b.js", chunk_idx=0),
    ]
    results = insert_batch(chunks)
    assert results[0] is not None
    assert results[1] is not None


def test_insert_batch_same_content_same_project_deduped():
    content = "const handler = async (req, res) => { res.json({ ok: true }); };"
    chunks = [
        ChunkInput(content=content, tags=["code"], project="/proj-x", source="code", source_ref="a.js", chunk_idx=0),
        ChunkInput(content=content, tags=["code"], project="/proj-x", source="code", source_ref="b.js", chunk_idx=0),
    ]
    results = insert_batch(chunks)
    stored = [r for r in results if r is not None]
    assert len(stored) == 1


def test_insert_batch_then_insert_cross_project_not_deduped():
    content = "function fibonacci(n) { return n <= 1 ? n : fibonacci(n-1) + fibonacci(n-2); }"
    chunks = [
        ChunkInput(content=content, tags=["code"], project="/alpha", source="code", source_ref="fib.js", chunk_idx=0),
    ]
    insert_batch(chunks)
    id_b = insert(content, tags=["code"], project="/beta", source="code")
    assert id_b is not None


def test_insert_batch_then_insert_same_project_deduped():
    content = "function fibonacci(n) { return n <= 1 ? n : fibonacci(n-1) + fibonacci(n-2); }"
    chunks = [
        ChunkInput(content=content, tags=["code"], project="/alpha", source="code", source_ref="fib.js", chunk_idx=0),
    ]
    insert_batch(chunks)
    id_dup = insert(content, tags=["code"], project="/alpha", source="code")
    assert id_dup is None


def test_empty_project_deduped_globally():
    content = "some globally unique content that should be deduplicated everywhere"
    id_a = insert(content, tags=["manual"], project="", source="manual")
    id_b = insert(content, tags=["manual"], project="", source="manual")
    assert id_a is not None
    assert id_b is None
