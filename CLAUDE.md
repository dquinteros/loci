# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**loci** is a local RAG (Retrieval-Augmented Generation) memory system for Claude Code. It runs as an MCP server and exposes Claude Code hooks to automatically capture, store, and retrieve project context across sessions using a local SQLite database with vector search.

## Commands

```bash
# Install in editable mode (required before running anything)
pip install -e .

# Register loci as an MCP server + hooks in ~/.claude/settings.json
loci install

# Index the current codebase into memory
loci index

# Watch ~/loci-docs for file changes and auto-ingest
loci watch

# Search memories
loci search "query" -k 5

# List memories for current project
loci list --tag session --limit 20

# Ingest a document or URL
loci add-doc path/to/file.pdf --tag reference
loci add-doc https://example.com --tag web

# Manually store a memory
loci add "some text to remember" --tag manual

# Start the MCP server (called by Claude Code automatically after loci install)
loci serve
```

No test suite or linter config exists yet. When adding tests, use pytest.

## Architecture

### Data Flow

```
User/Claude Code
      │
      ├─ MCP tools (loci serve) ──────────────────► mcp_server.py
      │                                              ↓
      ├─ CLI commands (loci add/search/index) ──► cli.py
      │                                              ↓
      └─ Claude Code hooks ──────────────────────► hooks/
                                                     ↓
                                              retriever.py / store.py
                                                     ↓
                                              ~/.loci/memories.db (SQLite)
```

### Core Modules

| Module | Responsibility |
|--------|---------------|
| `loci/store.py` | SQLite schema, CRUD, FTS5 index, sqlite-vec vector index, deduplication |
| `loci/embedder.py` | Wraps FastEmbed (`BAAI/bge-small-en-v1.5`, 384-dim) — singleton model |
| `loci/chunker.py` | Recursive character text splitter (default 1024 chars) |
| `loci/retriever.py` | Hybrid search: vector ANN + FTS5 keyword, merged via reciprocal rank fusion |
| `loci/mcp_server.py` | FastMCP server exposing `remember`, `recall`, `forget`, `list_memories` tools |
| `loci/config.py` | All constants (paths, thresholds, model name, extensions) |
| `loci/ingest/` | Source-specific ingestion: `code.py`, `pdf.py`, `docx.py`, `web.py`, `watcher.py` |

### Hooks (Claude Code Integration)

Registered by `loci install` into `~/.claude/settings.json`:

- `hooks/session_start.py` — runs at session start, injects top-5 project memories as `<loci-context>` into stdin
- `hooks/post_tool_use.py` — runs after every file edit, stores changed file content as a code memory
- `hooks/session_stop.py` — runs when Claude Code stops, saves session summary lines as "session"-tagged memories

### Storage Schema

Single SQLite DB at `~/.loci/memories.db` (overridable via `LOCI_DB_PATH`):
- `memories` table — content, JSON tags, project path, source type, source_ref (file path), chunk_idx
- `memories_fts` — FTS5 virtual table, auto-synced via triggers
- `memories_vec` — sqlite-vec virtual table for ANN (float32[384])

### Key Design Decisions

- **Deduplication threshold:** cosine similarity ≥ 0.95 skips storing duplicate chunks (`store.py`)
- **Project scoping:** memories are keyed to the git repo root (or CWD), so `recall` only returns relevant project context by default
- **Hybrid retrieval:** RRF merges vector and keyword rankings — neither alone is used; both contribute
- **Embedding model is a singleton:** loaded once in `embedder.py`, shared across the process to avoid reload overhead
