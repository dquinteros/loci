from __future__ import annotations
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import store, retriever, refs
from .store import init_db

mcp = FastMCP("loci")


@mcp.tool()
def remember(content: str, tags: list[str] = [], project: str = "") -> str:
    """Store a fact or note in persistent memory."""
    init_db()
    mem_id = store.insert(
        content,
        tags=tags,
        project=project or str(Path.cwd()),
        source="manual",
    )
    return f"stored:{mem_id}" if mem_id else "duplicate:skipped"


@mcp.tool()
def recall(query: str, k: int = 5, source: str = "", tags: list[str] = []) -> list[dict]:
    """Retrieve the most relevant memories for a query. Optionally filter by source type or tags."""
    init_db()
    memories = retriever.hybrid_search(
        query, k=k, project=str(Path.cwd()),
        source=source or None, tags=tags or None,
    )
    return [m.to_dict() for m in memories]


@mcp.tool()
def forget(id: str) -> str:
    """Delete a memory by id."""
    init_db()
    store.delete(id)
    return f"deleted:{id}"


@mcp.tool()
def list_memories(tag: str = "", limit: int = 20) -> list[dict]:
    """List memories for this project, optionally filtered by tag."""
    init_db()
    memories = store.list_memories(project=str(Path.cwd()), tag=tag, limit=limit)
    return [m.to_dict() for m in memories]


@mcp.tool()
def index_codebase(force: bool = False) -> str:
    """Index (or incrementally update) the current project codebase.
    Set force=True to reindex all files even if unchanged."""
    init_db()
    from .ingest import code as code_ingest
    added, skipped = code_ingest.ingest_codebase(
        Path.cwd(), project=str(Path.cwd()), incremental=not force
    )
    return f"indexed {added} new chunks ({skipped} files unchanged)"


@mcp.tool()
def add_ref(target_project: str) -> str:
    """Add a cross-project reference so this project's searches include the target."""
    init_db()
    resolved = str(Path(target_project).resolve())
    added = refs.add_ref(str(Path.cwd()), resolved)
    return f"added:{resolved}" if added else f"exists:{resolved}"


@mcp.tool()
def remove_ref(target_project: str) -> str:
    """Remove a cross-project reference."""
    init_db()
    resolved = str(Path(target_project).resolve())
    removed = refs.remove_ref(str(Path.cwd()), resolved)
    return f"removed:{resolved}" if removed else f"not_found:{resolved}"


@mcp.tool()
def list_refs() -> list[dict]:
    """List all cross-project references for this project."""
    init_db()
    entries = refs.list_refs(str(Path.cwd()))
    return [{"project": dst, "created_at": ts} for _, dst, ts in entries]


@mcp.tool()
def index_ref(target_project: str, force: bool = False) -> str:
    """Index a referenced project's codebase. Automatically adds the ref if missing."""
    init_db()
    from .ingest import code as code_ingest
    resolved = Path(target_project).resolve()
    refs.add_ref(str(Path.cwd()), str(resolved))
    added, skipped = code_ingest.ingest_codebase(
        resolved, project=str(resolved), incremental=not force
    )
    return f"indexed {added} new chunks from {resolved} ({skipped} files unchanged)"


@mcp.tool()
def find_files(query: str, k: int = 10) -> list[dict]:
    """Find project files by name or symbol. Returns file paths, symbols, and relevance scores."""
    init_db()
    from .embedder import embed
    q_emb = embed([query])[0]
    hits = store.file_index_search(q_emb, k=k, project=str(Path.cwd()))
    return [
        {"file_path": fp, "symbols": syms, "score": round(sc, 3)}
        for fp, syms, sc in hits
    ]


def serve() -> None:
    init_db()
    mcp.run()
