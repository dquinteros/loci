"""Tests for the schema migration system."""
from __future__ import annotations

import os
import sqlite3
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
    yield db_path
    _store.close()


def test_init_db_creates_schema_version_table(_isolated_db):
    from loci.store import init_db, _connect
    init_db()
    con = _connect()
    row = con.execute("SELECT MAX(version) FROM _schema_version").fetchone()
    assert row[0] >= 1


def test_init_db_creates_memories_table(_isolated_db):
    from loci.store import init_db, _connect
    init_db()
    con = _connect()
    tables = {
        r["name"]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "memories" in tables
    assert "project_refs" in tables
    assert "file_index" in tables


def test_init_db_is_idempotent(_isolated_db):
    from loci.store import init_db, _connect
    init_db()
    con = _connect()
    count_before = con.execute("SELECT COUNT(*) FROM _schema_version").fetchone()[0]
    init_db()
    count_after = con.execute("SELECT COUNT(*) FROM _schema_version").fetchone()[0]
    assert count_before == count_after


def test_migration_runner_skips_applied(tmp_path, monkeypatch):
    """Verify that re-running migrations doesn't duplicate version entries."""
    from loci import migrations
    from loci.store import _connect, init_db

    init_db()
    con = _connect()
    count_before = con.execute("SELECT COUNT(*) FROM _schema_version").fetchone()[0]
    applied = migrations.run_pending(con)
    count_after = con.execute("SELECT COUNT(*) FROM _schema_version").fetchone()[0]
    assert applied == 0
    assert count_before == count_after


def test_wal_mode_enabled(_isolated_db):
    from loci.store import init_db, _connect
    init_db()
    con = _connect()
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
