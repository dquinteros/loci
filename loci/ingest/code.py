from __future__ import annotations
from pathlib import Path

from .. import config, store
from ..chunker import chunk

_GITIGNORE_PATTERNS: list[str] = []


def _load_gitignore(cwd: Path) -> list[str]:
    gi = cwd / ".gitignore"
    if not gi.exists():
        return []
    patterns = []
    for line in gi.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(path: Path, patterns: list[str], cwd: Path) -> bool:
    import fnmatch
    rel = str(path.relative_to(cwd))
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat):
            return True
    return False


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
) -> tuple[int, int]:  # (chunks_added, files_skipped)
    cwd = Path(cwd)
    patterns = _load_gitignore(cwd)
    total = 0
    skipped = 0
    for path in cwd.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in config.CODE_EXTENSIONS:
            continue
        if _is_ignored(path, patterns, cwd):
            continue
        if any(part.startswith(".") for part in path.parts):
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
