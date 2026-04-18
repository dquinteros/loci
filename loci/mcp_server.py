from __future__ import annotations
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import store, retriever
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
def recall(query: str, k: int = 5) -> list[dict]:
    """Retrieve the most relevant memories for a query."""
    init_db()
    memories = retriever.hybrid_search(query, k=k, project=str(Path.cwd()))
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


def serve() -> None:
    init_db()
    mcp.run()
