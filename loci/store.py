from __future__ import annotations
import json
import sqlite3
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from time import time
from typing import Optional

import numpy as np

from . import config


@dataclass
class Memory:
    id: str
    content: str
    tags: list[str]
    project: str
    source: str
    source_ref: str
    chunk_idx: int
    created_at: float
    is_stale: int

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = json.loads(d["tags"]) if isinstance(d["tags"], str) else d["tags"]
        return d


def _connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    import sqlite_vec
    try:
        con.enable_load_extension(True)
    except AttributeError:
        raise RuntimeError(
            "Python was built without SQLite extension support. "
            "On macOS, install Homebrew SQLite and rebuild: "
            "brew install sqlite && "
            "PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' "
            "LDFLAGS='-L$(brew --prefix sqlite)/lib' "
            "CPPFLAGS='-I$(brew --prefix sqlite)/include' "
            "pyenv install --force <version>"
        ) from None
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    return con


def init_db() -> None:
    con = _connect()
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
    """)
    con.commit()
    con.close()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def insert(
    content: str,
    tags: list[str] | None = None,
    project: str = "",
    source: str = "manual",
    source_ref: str = "",
    chunk_idx: int = 0,
) -> Optional[str]:
    from .embedder import embed

    tags = tags or []
    emb = embed([content])[0]

    # dedup check
    hits = vector_search(emb, k=1, project=None)
    if hits:
        top_id, top_score = hits[0]
        if top_score >= config.DEDUP_COS:
            return None

    memory_id = str(uuid.uuid4())
    tags_json = json.dumps(tags)
    emb_bytes = emb.astype(np.float32).tobytes()

    con = _connect()
    try:
        row = con.execute("SELECT MAX(rowid) FROM memories").fetchone()
        next_rowid = (row[0] or 0) + 1
        con.execute(
            "INSERT INTO memories(id, content, tags, project, source, source_ref, chunk_idx, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (memory_id, content, tags_json, project, source, source_ref, chunk_idx, time()),
        )
        con.execute(
            "INSERT INTO memories_vec(rowid, embedding) VALUES (?,?)",
            (next_rowid, emb_bytes),
        )
        con.commit()
    finally:
        con.close()
    return memory_id


def delete(memory_id: str) -> None:
    con = _connect()
    try:
        row = con.execute("SELECT rowid FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row:
            rowid = row[0]
            con.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            con.execute("DELETE FROM memories_vec WHERE rowid=?", (rowid,))
            con.commit()
    finally:
        con.close()


def mark_stale(source_ref: str) -> None:
    con = _connect()
    try:
        con.execute("UPDATE memories SET is_stale=1 WHERE source_ref=?", (source_ref,))
        con.commit()
    finally:
        con.close()


def delete_stale(source_ref: str) -> None:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT id, rowid FROM memories WHERE source_ref=? AND is_stale=1", (source_ref,)
        ).fetchall()
        for row in rows:
            con.execute("DELETE FROM memories WHERE id=?", (row["id"],))
            con.execute("DELETE FROM memories_vec WHERE rowid=?", (row["rowid"],))
        con.commit()
    finally:
        con.close()


def last_indexed(source_ref: str) -> float | None:
    con = _connect()
    try:
        row = con.execute(
            "SELECT MAX(created_at) FROM memories WHERE source_ref = ?",
            (source_ref,),
        ).fetchone()
        return row[0] if row and row[0] is not None else None
    finally:
        con.close()


def vector_search(
    emb: np.ndarray, k: int = config.TOP_K, project: str | None = None
) -> list[tuple[str, float]]:
    emb_bytes = emb.astype(np.float32).tobytes()
    con = _connect()
    try:
        rows = con.execute(
            "SELECT rowid, distance FROM memories_vec WHERE embedding MATCH ? AND k=?",
            (emb_bytes, k * 3 if project else k),
        ).fetchall()
        if not rows:
            return []
        rowids = [r["rowid"] for r in rows]
        dist_map = {r["rowid"]: r["distance"] for r in rows}

        placeholders = ",".join("?" * len(rowids))
        query = f"SELECT id, rowid, project FROM memories WHERE rowid IN ({placeholders})"
        mem_rows = con.execute(query, rowids).fetchall()

        results = []
        for mr in mem_rows:
            if project and mr["project"] != project:
                continue
            dist = dist_map[mr["rowid"]]
            score = max(0.0, 1.0 - dist)
            results.append((mr["id"], score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
    finally:
        con.close()


def fts_search(
    query: str, k: int = config.TOP_K, project: str | None = None
) -> list[tuple[str, float]]:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT m.id, m.project, rank FROM memories_fts f"
            " JOIN memories m ON m.rowid = f.rowid"
            " WHERE memories_fts MATCH ?"
            " ORDER BY rank LIMIT ?",
            (query, k * 3 if project else k),
        ).fetchall()
        results = []
        for row in rows:
            if project and row["project"] != project:
                continue
            results.append((row["id"], -row["rank"]))
        return results[:k]
    finally:
        con.close()


def get_by_ids(ids: list[str]) -> list[Memory]:
    if not ids:
        return []
    con = _connect()
    try:
        placeholders = ",".join("?" * len(ids))
        rows = con.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders})", ids
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        result = []
        for memory_id in ids:
            if memory_id in by_id:
                r = by_id[memory_id]
                result.append(Memory(
                    id=r["id"],
                    content=r["content"],
                    tags=json.loads(r["tags"] or "[]"),
                    project=r["project"] or "",
                    source=r["source"] or "",
                    source_ref=r["source_ref"] or "",
                    chunk_idx=r["chunk_idx"] or 0,
                    created_at=r["created_at"] or 0.0,
                    is_stale=r["is_stale"] or 0,
                ))
        return result
    finally:
        con.close()


def list_memories(
    project: str = "", tag: str = "", limit: int = 20
) -> list[Memory]:
    con = _connect()
    try:
        conditions = ["1=1"]
        params: list = []
        if project:
            conditions.append("project=?")
            params.append(project)
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        params.append(limit)
        rows = con.execute(
            f"SELECT * FROM memories WHERE {' AND '.join(conditions)}"
            " ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            Memory(
                id=r["id"],
                content=r["content"],
                tags=json.loads(r["tags"] or "[]"),
                project=r["project"] or "",
                source=r["source"] or "",
                source_ref=r["source_ref"] or "",
                chunk_idx=r["chunk_idx"] or 0,
                created_at=r["created_at"] or 0.0,
                is_stale=r["is_stale"] or 0,
            )
            for r in rows
        ]
    finally:
        con.close()
