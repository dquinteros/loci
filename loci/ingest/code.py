from __future__ import annotations
import os
from pathlib import Path

import pathspec

from .. import config, store
from ..chunker import chunk


def _load_gitignore(cwd: Path) -> pathspec.PathSpec:
    gi = cwd / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _is_ignored(path: Path, spec: pathspec.PathSpec, cwd: Path) -> bool:
    rel = str(path.relative_to(cwd))
    return spec.match_file(rel)


def ingest_file(path: str | Path, project: str = "") -> int:
    path = Path(path)
    if path.suffix not in config.CODE_EXTENSIONS:
        return 0
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return 0
    chunks = chunk(text, size=2048)
    count = 0
    for idx, c in enumerate(chunks):
        if store.insert(c, tags=["code", path.suffix.lstrip(".")],
                        project=project, source="code",
                        source_ref=str(path), chunk_idx=idx):
            count += 1
    return count


def ingest_codebase(
    cwd: str | Path,
    project: str = "",
    incremental: bool = True,
) -> tuple[int, int]:
    cwd = Path(cwd)
    spec = _load_gitignore(cwd)
    total = 0
    skipped = 0

    for dirpath, dirnames, filenames in os.walk(cwd, topdown=True):
        dirnames[:] = [
            d for d in dirnames
            if d not in config.SKIP_DIRS
            and not d.startswith(".")
            and not _is_ignored(Path(dirpath) / d / "", spec, cwd)
        ]

        for fname in filenames:
            path = Path(dirpath) / fname
            if path.suffix not in config.CODE_EXTENSIONS:
                continue
            if _is_ignored(path, spec, cwd):
                continue

            if incremental:
                last = store.last_indexed(str(path))
                if last is not None and path.stat().st_mtime <= last:
                    skipped += 1
                    continue
                if last is not None:
                    store.mark_stale(str(path))
                total += ingest_file(path, project=project)
                if last is not None:
                    store.delete_stale(str(path))
            else:
                store.mark_stale(str(path))
                total += ingest_file(path, project=project)
                store.delete_stale(str(path))

    return total, skipped
