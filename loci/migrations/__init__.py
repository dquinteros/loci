"""Schema migration runner for loci's SQLite database.

Discovers migration modules in this package (named NNNN_*.py),
tracks applied versions in a _schema_version table, and runs
any pending migrations in order.
"""
from __future__ import annotations

import importlib
import pkgutil
import sqlite3
from pathlib import Path


def _discover_migrations() -> list[tuple[int, str]]:
    """Return sorted [(version, module_name), ...] for all migration files."""
    package_dir = Path(__file__).parent
    migrations = []
    for info in pkgutil.iter_modules([str(package_dir)]):
        name = info.name
        if name[0].isdigit() and "_" in name:
            version = int(name.split("_", 1)[0])
            migrations.append((version, name))
    migrations.sort()
    return migrations


def _current_version(con: sqlite3.Connection) -> int:
    con.execute(
        "CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER NOT NULL)"
    )
    row = con.execute("SELECT MAX(version) FROM _schema_version").fetchone()
    return row[0] or 0


def run_pending(con: sqlite3.Connection) -> int:
    """Run all pending migrations. Returns the number of migrations applied."""
    current = _current_version(con)
    applied = 0
    for version, module_name in _discover_migrations():
        if version <= current:
            continue
        mod = importlib.import_module(f".{module_name}", package=__name__)
        mod.up(con)
        con.execute("INSERT INTO _schema_version VALUES (?)", (version,))
        applied += 1
    if applied:
        con.commit()
    return applied
