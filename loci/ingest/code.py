from __future__ import annotations
import hashlib
import os
import re
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


_SYMBOL_PATTERNS: dict[str, str] = {
    ".py": r"(?:def|class)\s+(\w+)",
    ".ts": r"(?:function|class|const|export\s+(?:default\s+)?(?:function|class|const))\s+(\w+)",
    ".tsx": r"(?:function|class|const|export\s+(?:default\s+)?(?:function|class|const))\s+(\w+)",
    ".js": r"(?:function|class|const|export\s+(?:default\s+)?(?:function|class|const))\s+(\w+)",
    ".jsx": r"(?:function|class|const|export\s+(?:default\s+)?(?:function|class|const))\s+(\w+)",
    ".go": r"(?:func|type)\s+(\w+)",
    ".rs": r"(?:fn|struct|enum|trait|impl)\s+(\w+)",
    ".java": r"(?:class|interface|enum)\s+(\w+)",
}


def _extract_symbols(text: str, suffix: str) -> str:
    pattern = _SYMBOL_PATTERNS.get(
        suffix, r"(?:def|class|function|fn|struct)\s+(\w+)"
    )
    symbols = re.findall(pattern, text)
    return ", ".join(dict.fromkeys(symbols))


def collect_file_chunks(path: Path, project: str = "") -> list[store.ChunkInput]:
    if path.suffix not in config.CODE_EXTENSIONS:
        return []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    chunks = chunk(text, size=2048)
    return [
        store.ChunkInput(
            content=c,
            tags=["code", path.suffix.lstrip(".")],
            project=project,
            source="code",
            source_ref=str(path),
            chunk_idx=idx,
        )
        for idx, c in enumerate(chunks)
    ]


def ingest_file(path: str | Path, project: str = "") -> int:
    chunks = collect_file_chunks(Path(path), project)
    if not chunks:
        return 0
    results = store.insert_batch(chunks)
    return sum(1 for r in results if r is not None)


def ingest_codebase(
    cwd: str | Path,
    project: str = "",
    incremental: bool = True,
) -> tuple[int, int]:
    from ..embedder import embed

    cwd = Path(cwd)
    spec = _load_gitignore(cwd)
    all_chunks: list[store.ChunkInput] = []
    files_to_clean: list[str] = []
    seen_paths: set[str] = set()
    file_index_batch: list[tuple[str, str, str, str, int]] = []
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

            seen_paths.add(str(path))

            if incremental:
                last = store.last_indexed(str(path))
                if last is not None and path.stat().st_mtime <= last:
                    skipped += 1
                    continue

            text = path.read_text(errors="replace")
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            symbols = _extract_symbols(text, path.suffix)
            line_count = text.count("\n") + 1
            embed_text = f"{path.name}: {symbols}"
            file_index_batch.append(
                (str(path), content_hash, symbols, embed_text, line_count)
            )

            store.mark_stale(str(path))
            all_chunks.extend(collect_file_chunks(path, project))
            files_to_clean.append(str(path))

    if file_index_batch:
        embed_texts = [item[3] for item in file_index_batch]
        file_embs = embed(embed_texts)
        for i, (fp, chash, syms, _, lc) in enumerate(file_index_batch):
            store.upsert_file_index(project, fp, chash, syms, lc, file_embs[i])

    total = 0
    if all_chunks:
        results = store.insert_batch(all_chunks)
        total = sum(1 for r in results if r is not None)

    for ref in files_to_clean:
        store.delete_stale(ref)

    store.cleanup_deleted_files(project, seen_paths)

    return total, skipped
