from __future__ import annotations
import atexit
import json
import sqlite3
import threading
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


@dataclass(frozen=True)
class ChunkInput:
    content: str
    tags: list[str]
    project: str
    source: str
    source_ref: str
    chunk_idx: int


_local = threading.local()


def _connect() -> sqlite3.Connection:
    con = getattr(_local, "con", None)
    if con is not None:
        return con
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
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
    _local.con = con
    return con


def close() -> None:
    con = getattr(_local, "con", None)
    if con is not None:
        con.close()
        _local.con = None


atexit.register(close)


def init_db() -> None:
    from . import migrations
    con = _connect()
    migrations.run_pending(con)


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

    hits = vector_search(emb, k=1, project=project or None)
    if hits:
        top_id, top_score = hits[0]
        threshold = config.DEDUP_THRESHOLD_INTRA if project else config.DEDUP_THRESHOLD
        if top_score >= threshold:
            return None

    memory_id = str(uuid.uuid4())
    tags_json = json.dumps(tags)
    emb_bytes = emb.astype(np.float32).tobytes()

    con = _connect()
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
    return memory_id


def insert_batch(chunks: list[ChunkInput]) -> list[str | None]:
    if not chunks:
        return []

    from .embedder import embed

    texts = [c.content for c in chunks]
    embeddings = embed(texts)

    con = _connect()

    from collections import defaultdict

    project_groups: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(chunks):
        project_groups[c.project].append(i)

    is_dup = np.zeros(len(chunks), dtype=bool)

    for proj, indices in project_groups.items():
        if proj:
            existing_rows = con.execute(
                "SELECT v.rowid, v.embedding FROM memories_vec v"
                " JOIN memories m ON m.rowid = v.rowid"
                " WHERE m.project = ? AND m.is_stale = 0",
                (proj,),
            ).fetchall()
        else:
            existing_rows = con.execute(
                "SELECT rowid, embedding FROM memories_vec"
            ).fetchall()

        if existing_rows:
            n_existing = len(existing_rows)
            if n_existing > 100_000:
                for idx in indices:
                    hits = vector_search(embeddings[idx], k=1, project=proj or None)
                    threshold = config.DEDUP_THRESHOLD_INTRA if proj else config.DEDUP_THRESHOLD
                    if hits and hits[0][1] >= threshold:
                        is_dup[idx] = True
            else:
                existing_embs = np.stack([
                    np.frombuffer(r["embedding"], dtype=np.float32)
                    for r in existing_rows
                ])
                group_embs = embeddings[indices]
                cos_sims = group_embs @ existing_embs.T
                l2_dists = np.sqrt(np.maximum(0.0, 2.0 - 2.0 * cos_sims))
                scores = 1.0 - l2_dists
                max_scores = scores.max(axis=1)
                threshold = config.DEDUP_THRESHOLD_INTRA if proj else config.DEDUP_THRESHOLD
                for local_i, global_i in enumerate(indices):
                    if max_scores[local_i] >= threshold:
                        is_dup[global_i] = True

        for local_i, global_i in enumerate(indices):
            if is_dup[global_i]:
                continue
            for local_j in range(local_i + 1, len(indices)):
                global_j = indices[local_j]
                if is_dup[global_j]:
                    continue
                cos_sim = float(embeddings[global_i] @ embeddings[global_j])
                l2_dist = (max(0.0, 2.0 - 2.0 * cos_sim)) ** 0.5
                intra_threshold = config.DEDUP_THRESHOLD_INTRA if proj else config.DEDUP_THRESHOLD
                if (1.0 - l2_dist) >= intra_threshold:
                    is_dup[global_j] = True

    results: list[str | None] = []
    now = time()
    row = con.execute("SELECT MAX(rowid) FROM memories").fetchone()
    next_rowid = (row[0] or 0) + 1

    for i, chunk_input in enumerate(chunks):
        if is_dup[i]:
            results.append(None)
            continue

        memory_id = str(uuid.uuid4())
        tags_json = json.dumps(chunk_input.tags)
        emb_bytes = embeddings[i].astype(np.float32).tobytes()

        con.execute(
            "INSERT INTO memories(id, content, tags, project, source, source_ref, chunk_idx, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (memory_id, chunk_input.content, tags_json, chunk_input.project,
             chunk_input.source, chunk_input.source_ref, chunk_input.chunk_idx, now),
        )
        con.execute(
            "INSERT INTO memories_vec(rowid, embedding) VALUES (?,?)",
            (next_rowid, emb_bytes),
        )
        next_rowid += 1
        results.append(memory_id)

    con.commit()
    return results


def delete(memory_id: str) -> None:
    con = _connect()
    row = con.execute("SELECT rowid FROM memories WHERE id=?", (memory_id,)).fetchone()
    if row:
        rowid = row[0]
        con.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        con.execute("DELETE FROM memories_vec WHERE rowid=?", (rowid,))
        con.commit()


def mark_stale(source_ref: str) -> None:
    con = _connect()
    con.execute("UPDATE memories SET is_stale=1 WHERE source_ref=?", (source_ref,))
    con.commit()


def delete_stale(source_ref: str) -> None:
    con = _connect()
    rows = con.execute(
        "SELECT id, rowid FROM memories WHERE source_ref=? AND is_stale=1", (source_ref,)
    ).fetchall()
    for row in rows:
        con.execute("DELETE FROM memories WHERE id=?", (row["id"],))
        con.execute("DELETE FROM memories_vec WHERE rowid=?", (row["rowid"],))
    con.commit()


def last_indexed(source_ref: str) -> float | None:
    con = _connect()
    row = con.execute(
        "SELECT MAX(created_at) FROM memories WHERE source_ref = ?",
        (source_ref,),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def vector_search(
    emb: np.ndarray,
    k: int = config.TOP_K,
    project: str | None = None,
    projects: list[str] | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
) -> list[tuple[str, float]]:
    allowed = set(projects) if projects else ({project} if project else None)
    emb_bytes = emb.astype(np.float32).tobytes()
    con = _connect()
    rows = con.execute(
        "SELECT rowid, distance FROM memories_vec WHERE embedding MATCH ? AND k=?",
        (emb_bytes, k * 3 if allowed else k),
    ).fetchall()
    if not rows:
        return []
    rowids = [r["rowid"] for r in rows]
    dist_map = {r["rowid"]: r["distance"] for r in rows}

    conditions = [f"rowid IN ({','.join('?' * len(rowids))})", "is_stale = 0"]
    params: list = list(rowids)
    if source:
        conditions.append("source = ?")
        params.append(source)
    if tags:
        tag_clauses = " OR ".join(["tags LIKE ?"] * len(tags))
        conditions.append(f"({tag_clauses})")
        params.extend(f'%"{t}"%' for t in tags)

    query = f"SELECT id, rowid, project FROM memories WHERE {' AND '.join(conditions)}"
    mem_rows = con.execute(query, params).fetchall()

    results = []
    for mr in mem_rows:
        if allowed and mr["project"] not in allowed:
            continue
        dist = dist_map[mr["rowid"]]
        score = max(0.0, 1.0 - dist)
        results.append((mr["id"], score))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:k]


def fts_search(
    query: str,
    k: int = config.TOP_K,
    project: str | None = None,
    projects: list[str] | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
) -> list[tuple[str, float]]:
    allowed = set(projects) if projects else ({project} if project else None)
    con = _connect()

    fts_query = (
        "SELECT m.id, m.project, rank FROM memories_fts f"
        " JOIN memories m ON m.rowid = f.rowid"
        " WHERE memories_fts MATCH ? AND m.is_stale = 0"
    )
    params: list = [query]
    if source:
        fts_query += " AND m.source = ?"
        params.append(source)
    if tags:
        tag_clauses = " OR ".join(["m.tags LIKE ?"] * len(tags))
        fts_query += f" AND ({tag_clauses})"
        params.extend(f'%"{t}"%' for t in tags)
    fts_query += " ORDER BY rank LIMIT ?"
    params.append(k * 3 if allowed else k)

    rows = con.execute(fts_query, params).fetchall()
    results = []
    for row in rows:
        if allowed and row["project"] not in allowed:
            continue
        results.append((row["id"], -row["rank"]))
    return results[:k]


def get_by_ids(ids: list[str]) -> list[Memory]:
    if not ids:
        return []
    con = _connect()
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


def list_memories(
    project: str = "", tag: str = "", limit: int = 20
) -> list[Memory]:
    con = _connect()
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


def upsert_file_index(
    project: str,
    file_path: str,
    content_hash: str,
    symbols: str,
    line_count: int,
    embedding: np.ndarray,
) -> bool:
    """Upsert a file_index entry. Returns True if changed, False if skipped (hash match)."""
    con = _connect()
    existing = con.execute(
        "SELECT id, content_hash FROM file_index WHERE project=? AND file_path=?",
        (project, file_path),
    ).fetchone()

    if existing and existing["content_hash"] == content_hash:
        return False

    emb_bytes = embedding.astype(np.float32).tobytes()
    now = time()

    if existing:
        fid = existing["id"]
        con.execute(
            "UPDATE file_index SET content_hash=?, symbols=?, line_count=?, indexed_at=?"
            " WHERE id=?",
            (content_hash, symbols, line_count, now, fid),
        )
        con.execute(
            "UPDATE file_index_vec SET embedding=? WHERE rowid=?", (emb_bytes, fid)
        )
    else:
        con.execute(
            "INSERT INTO file_index(project, file_path, content_hash, symbols, line_count, indexed_at)"
            " VALUES (?,?,?,?,?,?)",
            (project, file_path, content_hash, symbols, line_count, now),
        )
        fid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute(
            "INSERT INTO file_index_vec(rowid, embedding) VALUES (?,?)",
            (fid, emb_bytes),
        )

    con.commit()
    return True


def cleanup_deleted_files(project: str, existing_paths: set[str]) -> int:
    """Remove chunks + file_index entries for files no longer on disk."""
    con = _connect()

    mem_refs = {
        r["source_ref"]
        for r in con.execute(
            "SELECT DISTINCT source_ref FROM memories WHERE project=? AND source='code'",
            (project,),
        ).fetchall()
    }
    fi_refs = {
        r["file_path"]
        for r in con.execute(
            "SELECT file_path FROM file_index WHERE project=?", (project,)
        ).fetchall()
    }
    deleted_refs = (mem_refs | fi_refs) - existing_paths
    if not deleted_refs:
        return 0

    for ref in deleted_refs:
        chunk_rows = con.execute(
            "SELECT rowid FROM memories WHERE project=? AND source_ref=?",
            (project, ref),
        ).fetchall()
        for cr in chunk_rows:
            con.execute("DELETE FROM memories_vec WHERE rowid=?", (cr["rowid"],))
        con.execute(
            "DELETE FROM memories WHERE project=? AND source_ref=?", (project, ref)
        )

        fi = con.execute(
            "SELECT id FROM file_index WHERE project=? AND file_path=?",
            (project, ref),
        ).fetchone()
        if fi:
            con.execute("DELETE FROM file_index_vec WHERE rowid=?", (fi["id"],))
            con.execute("DELETE FROM file_index WHERE id=?", (fi["id"],))

    con.commit()
    return len(deleted_refs)


def file_index_search(
    emb: np.ndarray,
    k: int = config.TOP_K,
    project: str | None = None,
) -> list[tuple[str, str, float]]:
    """Returns [(file_path, symbols, score), ...]."""
    con = _connect()
    emb_bytes = emb.astype(np.float32).tobytes()
    rows = con.execute(
        "SELECT rowid, distance FROM file_index_vec WHERE embedding MATCH ? AND k=?",
        (emb_bytes, k * 2 if project else k),
    ).fetchall()
    if not rows:
        return []
    rowids = [r["rowid"] for r in rows]
    dist_map = {r["rowid"]: r["distance"] for r in rows}

    placeholders = ",".join("?" * len(rowids))
    fi_rows = con.execute(
        f"SELECT id, file_path, symbols, project FROM file_index WHERE id IN ({placeholders})",
        rowids,
    ).fetchall()

    results = []
    for fr in fi_rows:
        if project and fr["project"] != project:
            continue
        score = max(0.0, 1.0 - dist_map[fr["id"]])
        results.append((fr["file_path"], fr["symbols"], score))
    results.sort(key=lambda x: x[2], reverse=True)
    return results[:k]


def get_chunk_ids_for_files(
    file_paths: list[str], project: str
) -> dict[str, list[str]]:
    """Return {source_ref: [memory_id, ...]} for given files."""
    if not file_paths:
        return {}
    con = _connect()
    placeholders = ",".join("?" * len(file_paths))
    rows = con.execute(
        f"SELECT id, source_ref FROM memories"
        f" WHERE project=? AND source_ref IN ({placeholders}) AND is_stale=0",
        [project] + file_paths,
    ).fetchall()
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["source_ref"], []).append(r["id"])
    return result
