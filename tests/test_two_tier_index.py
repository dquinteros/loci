"""Tests for two-tier code index: stale exclusion, intra-project threshold, file_index, cleanup."""
from __future__ import annotations

import os
import threading

import numpy as np
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


from loci import store, config
from loci.store import (
    insert,
    insert_batch,
    ChunkInput,
    mark_stale,
    delete_stale,
    vector_search,
    fts_search,
    upsert_file_index,
    cleanup_deleted_files,
    file_index_search,
    get_chunk_ids_for_files,
)


def _make_emb(seed: int = 0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    v = rng.randn(384).astype(np.float32)
    return v / np.linalg.norm(v)


def test_force_reindex_no_self_dedup():
    """mark_stale + insert_batch should not dedup against stale rows."""
    content = "def compute_fibonacci(n): return n if n <= 1 else compute_fibonacci(n-1) + compute_fibonacci(n-2)"
    chunks = [
        ChunkInput(content=content, tags=["code"], project="/proj", source="code", source_ref="/proj/fib.py", chunk_idx=0),
    ]
    results1 = insert_batch(chunks)
    assert results1[0] is not None

    mark_stale("/proj/fib.py")

    results2 = insert_batch(chunks)
    assert results2[0] is not None, "New chunk should not be deduped against stale rows"

    delete_stale("/proj/fib.py")

    from loci.embedder import embed
    emb = embed([content])[0]
    hits = vector_search(emb, k=10, project="/proj")
    assert len(hits) == 1, "After cleanup only the new chunk remains"


def test_stale_excluded_from_vector_search():
    content = "async function fetchData() { return await fetch('/api/data'); }"
    mid = insert(content, tags=["code"], project="/proj", source="code", source_ref="/proj/api.js")
    assert mid is not None

    from loci.embedder import embed
    emb = embed([content])[0]
    hits = vector_search(emb, k=5, project="/proj")
    assert any(h[0] == mid for h in hits)

    mark_stale("/proj/api.js")
    hits_after = vector_search(emb, k=5, project="/proj")
    assert not any(h[0] == mid for h in hits_after), "Stale rows must not appear in vector_search"


def test_stale_excluded_from_fts_search():
    content = "def unique_xyzzy_function(): pass"
    mid = insert(content, tags=["code"], project="/proj", source="code", source_ref="/proj/x.py")
    assert mid is not None

    hits = fts_search("unique_xyzzy_function", k=5, project="/proj")
    assert any(h[0] == mid for h in hits)

    mark_stale("/proj/x.py")
    hits_after = fts_search("unique_xyzzy_function", k=5, project="/proj")
    assert not any(h[0] == mid for h in hits_after), "Stale rows must not appear in fts_search"


def _make_similar_pair(target_score: float):
    """Create two unit vectors whose 1-L2_distance score equals target_score."""
    v1 = np.zeros(384, dtype=np.float32)
    v1[0] = 1.0
    l2 = 1.0 - target_score
    cos = 1.0 - (l2 ** 2) / 2.0
    v2 = np.zeros(384, dtype=np.float32)
    v2[0] = cos
    v2[1] = np.sqrt(max(0.0, 1.0 - cos ** 2))
    return v1, v2


def test_intra_project_threshold(monkeypatch):
    """Score 0.97 (between 0.95 and 0.99) should NOT be deduped intra-project."""
    e1, e2 = _make_similar_pair(0.97)
    calls = iter([np.array([e1]), np.array([e2])])
    monkeypatch.setattr("loci.embedder.embed", lambda texts: next(calls))

    id_a = insert("content_a", tags=["code"], project="/proj", source="code")
    id_b = insert("content_b", tags=["code"], project="/proj", source="code")
    assert id_a is not None
    assert id_b is not None, "Score 0.97 < DEDUP_THRESHOLD_INTRA(0.99) so both should be stored"


def test_global_dedup_uses_original_threshold(monkeypatch):
    """Score 0.97 with empty project should be deduped (>= DEDUP_THRESHOLD 0.95)."""
    e1, e2 = _make_similar_pair(0.97)
    calls = iter([np.array([e1]), np.array([e2])])
    monkeypatch.setattr("loci.embedder.embed", lambda texts: next(calls))

    id_a = insert("content_a", tags=["manual"], project="", source="manual")
    id_b = insert("content_b", tags=["manual"], project="", source="manual")
    assert id_a is not None
    assert id_b is None, "Score 0.97 >= DEDUP_THRESHOLD(0.95) so global insert should dedup"


def test_file_index_upsert_and_skip():
    emb = _make_emb(42)
    changed = upsert_file_index("/proj", "/proj/foo.py", "hash1", "foo, bar", 100, emb)
    assert changed is True

    skipped = upsert_file_index("/proj", "/proj/foo.py", "hash1", "foo, bar", 100, emb)
    assert skipped is False, "Same hash should be skipped"

    emb2 = _make_emb(43)
    updated = upsert_file_index("/proj", "/proj/foo.py", "hash2", "foo, bar, baz", 120, emb2)
    assert updated is True, "Different hash should trigger update"


def test_cleanup_deleted_files():
    emb = _make_emb(10)
    for fname in ["a.py", "b.py", "c.py"]:
        ref = f"/proj/{fname}"
        insert(
            f"content of {fname}", tags=["code"], project="/proj",
            source="code", source_ref=ref,
        )
        upsert_file_index("/proj", ref, f"hash_{fname}", fname, 10, emb)

    deleted = cleanup_deleted_files("/proj", {"/proj/a.py", "/proj/b.py"})
    assert deleted == 1

    con = store._connect()
    remaining_mem = con.execute(
        "SELECT DISTINCT source_ref FROM memories WHERE project='/proj' AND source='code'"
    ).fetchall()
    remaining_refs = {r["source_ref"] for r in remaining_mem}
    assert "/proj/c.py" not in remaining_refs

    fi_row = con.execute(
        "SELECT * FROM file_index WHERE project='/proj' AND file_path='/proj/c.py'"
    ).fetchone()
    assert fi_row is None, "file_index entry for deleted file should be removed"


def test_file_index_search():
    from loci.embedder import embed

    entries = [
        ("/proj/auth.py", "authenticate, login, verify_token"),
        ("/proj/db.py", "connect, query, migrate"),
        ("/proj/utils.py", "format_date, parse_json"),
    ]
    texts = [f"{Path(fp).name}: {syms}" for fp, syms in entries]
    embs = embed(texts)
    for i, (fp, syms) in enumerate(entries):
        upsert_file_index("/proj", fp, f"hash{i}", syms, 50, embs[i])

    q_emb = embed(["authentication login token"])[0]
    hits = file_index_search(q_emb, k=3, project="/proj")
    assert len(hits) > 0
    assert hits[0][0] == "/proj/auth.py", f"Expected auth.py as top hit, got {hits[0][0]}"


from pathlib import Path
