from __future__ import annotations

from collections import deque
from pathlib import Path
from time import time

from . import store


def _normalize(path: str) -> str:
    return str(Path(path).resolve())


def add_ref(src: str, dst: str) -> bool:
    src, dst = _normalize(src), _normalize(dst)
    con = store._connect()
    cur = con.execute(
        "INSERT OR IGNORE INTO project_refs (src_project, dst_project, created_at)"
        " VALUES (?, ?, ?)",
        (src, dst, time()),
    )
    con.commit()
    return cur.rowcount > 0


def remove_ref(src: str, dst: str) -> bool:
    src, dst = _normalize(src), _normalize(dst)
    con = store._connect()
    cur = con.execute(
        "DELETE FROM project_refs WHERE src_project = ? AND dst_project = ?",
        (src, dst),
    )
    con.commit()
    return cur.rowcount > 0


def list_refs(project: str) -> list[tuple[str, str, float]]:
    project = _normalize(project)
    con = store._connect()
    rows = con.execute(
        "SELECT src_project, dst_project, created_at"
        " FROM project_refs WHERE src_project = ?",
        (project,),
    ).fetchall()
    return [(r["src_project"], r["dst_project"], r["created_at"]) for r in rows]


def resolve_projects(project: str, max_depth: int = 2) -> list[str]:
    project = _normalize(project)
    visited: set[str] = {project}
    queue: deque[tuple[str, int]] = deque([(project, 0)])
    result = [project]

    con = store._connect()
    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        rows = con.execute(
            "SELECT dst_project FROM project_refs WHERE src_project = ?",
            (node,),
        ).fetchall()
        for r in rows:
            dst = r["dst_project"]
            if dst not in visited:
                visited.add(dst)
                result.append(dst)
                queue.append((dst, depth + 1))

    return result
