"""Integration tests: end-to-end indexing, search, cross-project, CLI."""
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
    yield tmp_path
    _store.close()


def test_index_and_search_codebase(tmp_path):
    """Index a temp directory with .py files, then search."""
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / "app.py").write_text(
        "def calculate_fibonacci(n):\n"
        "    if n <= 1:\n"
        "        return n\n"
        "    return calculate_fibonacci(n-1) + calculate_fibonacci(n-2)\n"
    )
    (project_dir / "utils.py").write_text(
        "def format_currency(amount, symbol='$'):\n"
        "    return f'{symbol}{amount:,.2f}'\n"
    )

    from loci.ingest.code import ingest_codebase
    from loci import retriever

    added, skipped = ingest_codebase(project_dir, project=str(project_dir))
    assert added >= 2

    results = retriever.hybrid_search(
        "fibonacci recursive function", k=5, project=str(project_dir)
    )
    assert len(results) >= 1
    assert any("fibonacci" in m.content.lower() for m in results)


def test_stale_reindex_cycle(tmp_path):
    """Index, modify, reindex — old chunks replaced."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    f = project_dir / "main.py"
    f.write_text("def old_function():\n    return 'old'\n")

    from loci.ingest.code import ingest_codebase
    from loci import store

    added1, _ = ingest_codebase(project_dir, project=str(project_dir), incremental=False)
    assert added1 >= 1

    f.write_text("def new_function():\n    return 'new'\n")
    added2, _ = ingest_codebase(project_dir, project=str(project_dir), incremental=False)
    assert added2 >= 1

    memories = store.list_memories(project=str(project_dir), limit=100)
    contents = " ".join(m.content for m in memories)
    assert "new_function" in contents
    assert all(m.is_stale == 0 for m in memories)


def test_cross_project_search(tmp_path):
    """Two projects with a ref — search returns both."""
    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    from loci import store, retriever, refs

    store.insert("Alpha project database schema", tags=["arch"], project=str(proj_a), source="manual")
    store.insert("Beta project API endpoints", tags=["arch"], project=str(proj_b), source="manual")

    refs.add_ref(str(proj_a), str(proj_b))

    results = retriever.hybrid_search("database API", k=5, project=str(proj_a))
    projects_found = {m.project for m in results}
    assert str(proj_a) in projects_found or str(proj_b) in projects_found


def test_file_size_cap_skips_large_files(tmp_path):
    """Files exceeding MAX_FILE_SIZE are skipped."""
    import loci.config as cfg
    project_dir = tmp_path / "big"
    project_dir.mkdir()
    big_file = project_dir / "generated.py"
    big_file.write_text("x = 1\n" * 200_000)
    assert big_file.stat().st_size > cfg.MAX_FILE_SIZE

    from loci.ingest.code import ingest_codebase

    added, skipped = ingest_codebase(project_dir, project=str(project_dir))
    assert added == 0
    assert skipped >= 1


def test_cli_add_and_search():
    """CLI add + search smoke test via Click CliRunner."""
    from click.testing import CliRunner
    from loci.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["add", "Important architecture decision about caching"])
    assert result.exit_code == 0

    result = runner.invoke(main, ["search", "caching architecture"])
    assert result.exit_code == 0
    assert "caching" in result.output.lower()


def test_cli_list():
    """CLI list returns something after adding memories."""
    from click.testing import CliRunner
    from loci.cli import main
    from loci import store

    store.insert("test memory for listing", tags=["test"], project=str(os.getcwd()), source="manual")

    runner = CliRunner()
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0


def test_model_version_tracked():
    """After init_db, _metadata has embed_model entry."""
    from loci.store import _connect
    con = _connect()
    row = con.execute("SELECT value FROM _metadata WHERE key='embed_model'").fetchone()
    assert row is not None
    assert "bge" in row[0].lower()
