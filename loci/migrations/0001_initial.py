"""Initial schema: memories, FTS5, sqlite-vec, project_refs, file_index."""
from __future__ import annotations

import sqlite3

VERSION = 1


def up(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id          TEXT PRIMARY KEY,
            content     TEXT NOT NULL,
            tags        TEXT DEFAULT '[]',
            project     TEXT,
            source      TEXT,
            source_ref  TEXT,
            chunk_idx   INTEGER DEFAULT 0,
            created_at  REAL,
            is_stale    INTEGER DEFAULT 0
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content, tags, content=memories, content_rowid=rowid
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
            embedding float[384]
        );

        CREATE TRIGGER IF NOT EXISTS memories_ai
        AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, tags)
            VALUES (new.rowid, new.content, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS memories_ad
        AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, tags)
            VALUES('delete', old.rowid, old.content, old.tags);
        END;

        CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project);

        CREATE TABLE IF NOT EXISTS project_refs (
            src_project TEXT NOT NULL,
            dst_project TEXT NOT NULL,
            created_at  REAL NOT NULL,
            PRIMARY KEY (src_project, dst_project)
        );

        CREATE TABLE IF NOT EXISTS file_index (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project     TEXT NOT NULL,
            file_path   TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            symbols     TEXT DEFAULT '',
            line_count  INTEGER DEFAULT 0,
            indexed_at  REAL NOT NULL,
            UNIQUE(project, file_path)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS file_index_vec USING vec0(
            embedding float[384]
        );

        CREATE INDEX IF NOT EXISTS idx_file_index_project ON file_index(project);
    """)
