"""Add _metadata table for tracking embedding model version."""
from __future__ import annotations

import sqlite3

VERSION = 2


def up(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS _metadata (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
