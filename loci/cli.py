from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import click

from . import config, store, retriever
from .store import init_db


@click.group()
def main() -> None:
    """loci — local RAG memory for Claude Code."""
    init_db()


@main.command("add")
@click.argument("text")
@click.option("--tag", "-t", multiple=True, help="Tag to attach")
def add_memory(text: str, tag: tuple[str, ...]) -> None:
    """Manually store a memory."""
    mem_id = store.insert(text, tags=list(tag), project=str(Path.cwd()), source="manual")
    if mem_id:
        click.echo(f"stored: {mem_id}")
    else:
        click.echo("duplicate: skipped")


@main.command("add-doc")
@click.argument("target")
@click.option("--tag", "-t", multiple=True)
def add_doc(target: str, tag: tuple[str, ...]) -> None:
    """Ingest a PDF, DOCX, Markdown, or web URL."""
    project = str(Path.cwd())
    if target.startswith("http://") or target.startswith("https://"):
        from .ingest import web as web_ingest
        count = web_ingest.ingest(target, project=project)
    else:
        path = Path(target)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            from .ingest import pdf as pdf_ingest
            count = pdf_ingest.ingest(path, project=project)
        elif suffix == ".docx":
            from .ingest import docx as docx_ingest
            count = docx_ingest.ingest(path, project=project)
        elif suffix in {".md", ".txt"}:
            from .chunker import chunk
            text = path.read_text(errors="replace")
            count = 0
            for idx, c in enumerate(chunk(text)):
                if store.insert(c, tags=list(tag) or ["doc"], project=project,
                                source="file", source_ref=str(path), chunk_idx=idx):
                    count += 1
        else:
            click.echo(f"Unsupported file type: {suffix}", err=True)
            sys.exit(1)
    click.echo(f"ingested {count} chunks from {target}")


@main.command("search")
@click.argument("query")
@click.option("-k", default=config.TOP_K, show_default=True, help="Number of results")
def search(query: str, k: int) -> None:
    """Hybrid search memories."""
    memories = retriever.hybrid_search(query, k=k, project=str(Path.cwd()))
    if not memories:
        click.echo("No results.")
        return
    for m in memories:
        click.echo(f"[{m.source}] {m.content[:120]!r}")
        if m.tags:
            click.echo(f"  tags: {m.tags}  id: {m.id}")


@main.command("list")
@click.option("--tag", "-t", default="")
@click.option("--limit", "-n", default=20, show_default=True)
def list_cmd(tag: str, limit: int) -> None:
    """List memories for the current project."""
    memories = store.list_memories(project=str(Path.cwd()), tag=tag, limit=limit)
    if not memories:
        click.echo("No memories.")
        return
    for m in memories:
        click.echo(f"[{m.id[:8]}] [{m.source}] {m.content[:100]!r}")


@main.command("index")
@click.option("--force", is_flag=True, default=False,
              help="Reindex all files even if unchanged")
def index_cmd(force: bool) -> None:
    """One-shot index of the current codebase."""
    from .ingest import code as code_ingest
    cwd = Path.cwd()
    added, skipped = code_ingest.ingest_codebase(
        cwd, project=str(cwd), incremental=not force
    )
    click.echo(f"indexed {added} new chunks ({skipped} files unchanged)")


@main.command("watch")
def watch_cmd() -> None:
    """Start background daemon watching ~/loci-docs/ and cwd for changes."""
    from .ingest.watcher import start_daemon
    start_daemon(project=str(Path.cwd()))


@main.command("export")
@click.option("--json", "as_json", is_flag=True, help="Export as JSON instead of DB path")
def export_cmd(as_json: bool) -> None:
    """Export the memories database."""
    if as_json:
        memories = store.list_memories(limit=100_000)
        click.echo(json.dumps([m.to_dict() for m in memories], indent=2))
    else:
        click.echo(str(config.DB_PATH))


@main.command("import")
@click.argument("db_path")
def import_cmd(db_path: str) -> None:
    """Merge memories from another DB file into the local store."""
    import sqlite3
    src = Path(db_path)
    if not src.exists():
        click.echo(f"File not found: {db_path}", err=True)
        sys.exit(1)

    src_con = sqlite3.connect(src)
    src_con.row_factory = sqlite3.Row
    rows = src_con.execute("SELECT * FROM memories").fetchall()
    src_con.close()

    count = 0
    for row in rows:
        tags = json.loads(row["tags"] or "[]")
        mem_id = store.insert(
            row["content"],
            tags=tags,
            project=row["project"] or "",
            source=row["source"] or "manual",
            source_ref=row["source_ref"] or "",
            chunk_idx=row["chunk_idx"] or 0,
        )
        if mem_id:
            count += 1
    click.echo(f"imported {count} memories (duplicates skipped)")


@main.command("serve")
def serve_cmd() -> None:
    """Start the MCP server (called by Claude Code)."""
    from .mcp_server import serve
    serve()


@main.command("install")
def install_cmd() -> None:
    """Configure ~/.claude/settings.json with MCP server and hooks."""
    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            pass

    hooks_dir = Path.home() / ".loci" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Copy hook scripts to ~/.loci/hooks/
    src_hooks = Path(__file__).parent.parent / "hooks"
    if src_hooks.exists():
        import shutil
        for hook_file in src_hooks.glob("*.py"):
            shutil.copy(hook_file, hooks_dir / hook_file.name)

    python = sys.executable
    hook_cmd = lambda name: f"{python} {hooks_dir / name}"

    existing.setdefault("mcpServers", {})
    existing["mcpServers"]["loci"] = {"type": "stdio", "command": "loci", "args": ["serve"]}

    existing.setdefault("hooks", {})
    existing["hooks"]["SessionStart"] = [
        {"hooks": [{"type": "command", "command": hook_cmd("session_start.py")}]}
    ]
    existing["hooks"]["Stop"] = [
        {"hooks": [{"type": "command", "command": hook_cmd("session_stop.py")}]}
    ]
    existing["hooks"]["PostToolUse"] = [
        {"hooks": [{"type": "command", "command": hook_cmd("post_tool_use.py")}]}
    ]

    settings_path.write_text(json.dumps(existing, indent=2))
    click.echo(f"installed loci hooks and MCP server in {settings_path}")
    click.echo(f"hook scripts copied to {hooks_dir}")
