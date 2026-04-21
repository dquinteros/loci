from __future__ import annotations
import json
import os
import sys
from pathlib import Path

import click

from . import config, store, retriever, refs
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
            chunks_input = [
                store.ChunkInput(
                    content=c, tags=list(tag) or ["doc"], project=project,
                    source="file", source_ref=str(path), chunk_idx=idx,
                )
                for idx, c in enumerate(chunk(text))
            ]
            results = store.insert_batch(chunks_input)
            count = sum(1 for r in results if r is not None)
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

    chunks_input = [
        store.ChunkInput(
            content=row["content"],
            tags=json.loads(row["tags"] or "[]"),
            project=row["project"] or "",
            source=row["source"] or "manual",
            source_ref=row["source_ref"] or "",
            chunk_idx=row["chunk_idx"] or 0,
        )
        for row in rows
    ]
    results = store.insert_batch(chunks_input)
    count = sum(1 for r in results if r is not None)
    click.echo(f"imported {count} memories (duplicates skipped)")


@main.group("ref")
def ref_group() -> None:
    """Manage cross-project references."""


@ref_group.command("add")
@click.argument("path")
def ref_add(path: str) -> None:
    """Add a reference to another project."""
    resolved = str(Path(path).resolve())
    if refs.add_ref(str(Path.cwd()), resolved):
        click.echo(f"added ref -> {resolved}")
    else:
        click.echo(f"ref already exists -> {resolved}")


@ref_group.command("remove")
@click.argument("path")
def ref_remove(path: str) -> None:
    """Remove a reference to another project."""
    resolved = str(Path(path).resolve())
    if refs.remove_ref(str(Path.cwd()), resolved):
        click.echo(f"removed ref -> {resolved}")
    else:
        click.echo(f"ref not found -> {resolved}")


@ref_group.command("list")
def ref_list() -> None:
    """List all project references."""
    entries = refs.list_refs(str(Path.cwd()))
    if not entries:
        click.echo("No references.")
        return
    for _, dst, _ in entries:
        click.echo(dst)


@main.command("index-ref")
@click.argument("path")
@click.option("--force", is_flag=True, default=False,
              help="Reindex all files even if unchanged")
def index_ref_cmd(path: str, force: bool) -> None:
    """Index a referenced project's codebase."""
    from .ingest import code as code_ingest
    resolved = Path(path).resolve()
    refs.add_ref(str(Path.cwd()), str(resolved))
    added, skipped = code_ingest.ingest_codebase(
        resolved, project=str(resolved), incremental=not force
    )
    click.echo(f"indexed {added} new chunks from {resolved} ({skipped} files unchanged)")


@main.command("serve")
def serve_cmd() -> None:
    """Start the MCP server (called by Claude Code)."""
    from .mcp_server import serve
    serve()


LOCI_HOOK_MARKER = "/.loci/hooks/"

LOCI_HOOKS = {
    "SessionStart": "session_start.py",
    "Stop": "session_stop.py",
    "PostToolUse": "post_tool_use.py",
    "UserPromptSubmit": "user_prompt_submit.py",
}


def _is_loci_hook_entry(entry: dict) -> bool:
    hooks = entry.get("hooks", [])
    return any(LOCI_HOOK_MARKER in h.get("command", "") for h in hooks)


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


@main.command("install")
def install_cmd() -> None:
    """Register loci MCP server and hooks with Claude Code."""
    import shutil

    loci_bin = str(Path(sys.executable).parent / "loci")
    python = sys.executable
    hooks_dir = Path.home() / ".loci" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    src_hooks = Path(__file__).parent / "hooks"
    copied = 0
    if src_hooks.is_dir():
        for hook_file in src_hooks.glob("*.py"):
            if hook_file.name == "__init__.py":
                continue
            shutil.copy(hook_file, hooks_dir / hook_file.name)
            copied += 1

    claude_json_path = Path.home() / ".claude.json"
    claude_cfg = _read_json(claude_json_path)
    claude_cfg.setdefault("mcpServers", {})
    claude_cfg["mcpServers"]["loci"] = {
        "type": "stdio",
        "command": loci_bin,
        "args": ["serve"],
    }
    _write_json(claude_json_path, claude_cfg)
    click.echo(f"registered MCP server in {claude_json_path}")

    settings_path = Path.home() / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    settings.pop("mcpServers", None)
    settings.setdefault("hooks", {})

    hook_cmd = lambda name: f"{python} {hooks_dir / name}"

    for event, script in LOCI_HOOKS.items():
        existing = settings["hooks"].get(event, [])
        filtered = [e for e in existing if not _is_loci_hook_entry(e)]
        loci_entry = {"hooks": [{"type": "command", "command": hook_cmd(script)}]}
        filtered.append(loci_entry)
        settings["hooks"][event] = filtered

    _write_json(settings_path, settings)
    click.echo(f"registered hooks in {settings_path}")
    if copied:
        click.echo(f"copied {copied} hook scripts to {hooks_dir}")
    else:
        click.echo(f"warning: no hook scripts found in {src_hooks}")


@main.command("uninstall")
def uninstall_cmd() -> None:
    """Remove loci MCP server and hooks from Claude Code."""
    claude_json_path = Path.home() / ".claude.json"
    claude_cfg = _read_json(claude_json_path)
    removed_mcp = False
    if "mcpServers" in claude_cfg and "loci" in claude_cfg["mcpServers"]:
        del claude_cfg["mcpServers"]["loci"]
        _write_json(claude_json_path, claude_cfg)
        removed_mcp = True
    click.echo(f"{'removed' if removed_mcp else 'no'} MCP server in {claude_json_path}")

    settings_path = Path.home() / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    hooks_changed = False
    for event in LOCI_HOOKS:
        existing = settings.get("hooks", {}).get(event, [])
        filtered = [e for e in existing if not _is_loci_hook_entry(e)]
        if len(filtered) != len(existing):
            hooks_changed = True
            settings.setdefault("hooks", {})[event] = filtered

    if hooks_changed:
        _write_json(settings_path, settings)
    click.echo(f"{'removed' if hooks_changed else 'no'} hooks in {settings_path}")
