# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**loci** is a local RAG (Retrieval-Augmented Generation) memory system for Claude Code. It runs as an MCP server and exposes Claude Code hooks to automatically capture, store, and retrieve project context across sessions using a local SQLite database with vector search.

## Commands

```bash
# One-liner remote install (handles Python/pyenv/SQLite setup)
curl -sSL https://raw.githubusercontent.com/dquinteros/loci/main/install.sh | bash

# Or install in editable mode for development
pip install -e .

# Register loci as an MCP server + hooks (safe to re-run, preserves other hooks)
loci install

# Remove loci MCP server and hooks from Claude Code
loci uninstall

# Index the current codebase into memory (incremental by default)
loci index

# Force full reindex of all files regardless of mtime
loci index --force

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

# Export / import
loci export            # print DB path
loci export --json     # dump all memories as JSON
loci import /path/to/other/memories.db

# Cross-project references
loci ref add ../other-project    # declare a reference to another project
loci ref remove ../other-project # remove a reference
loci ref list                    # list all references from this project

# Index a referenced project's codebase (auto-adds the ref)
loci index-ref ../other-project
loci index-ref ../other-project --force

# Start the MCP server (called by Claude Code automatically after loci install)
loci serve
```

Tests use pytest: `pytest tests/ -v`. Dev dependencies: `pip install -e ".[dev]"`

## Architecture

### Data Flow

```
User/Claude Code
      │
      ├─ MCP tools (loci serve) ──────────────────► mcp_server.py
      │                                              ↓
      ├─ CLI commands (loci add/search/ref/…) ──► cli.py
      │                                              ↓
      └─ Claude Code hooks ──────────────────────► loci/hooks/
                                                     ↓
                                              retriever.py / store.py
                                                     ↓        ↑
                                              refs.py (cross-project graph)
                                                     ↓
                                              ~/.loci/memories.db (SQLite)
```

### Core Modules

| Module | Responsibility |
|--------|---------------|
| `loci/store.py` | CRUD, FTS5 index, sqlite-vec vector index, deduplication, batch insert, thread-local connection pool |
| `loci/migrations/` | Numbered schema migrations (`0001_initial.py`, etc.) with version tracking in `_schema_version` table |
| `loci/embedder.py` | Wraps FastEmbed (`BAAI/bge-small-en-v1.5`, 384-dim) — singleton model |
| `loci/chunker.py` | Recursive character text splitter (default 1024 chars / 200-char overlap, code uses 2048) |
| `loci/refs.py` | Cross-project reference graph: CRUD + BFS resolver for multi-project search |
| `loci/retriever.py` | Hybrid search: vector ANN + FTS5 keyword, merged via reciprocal rank fusion |
| `loci/mcp_server.py` | FastMCP server exposing `remember`, `recall`, `forget`, `list_memories`, `index_codebase`, `add_ref`, `remove_ref`, `list_refs`, `index_ref` tools |
| `loci/cli.py` | Click CLI: all user-facing commands including `install`/`uninstall`, `ref` subgroup, `index-ref` |
| `loci/config.py` | All constants (paths, thresholds, boosts, model name, extensions, `SKIP_DIRS`, `MAX_FILE_SIZE`) |
| `loci/ingest/` | Source-specific ingestion: `code.py`, `pdf.py`, `docx.py`, `web.py`, `watcher.py` |
| `loci/hooks/` | Hook scripts bundled inside the package; `loci install` copies them to `~/.loci/hooks/` |

### Hooks (Claude Code Integration)

`loci install` registers the MCP server in `~/.claude.json` (where Claude Code reads `mcpServers`), copies hook scripts from `loci/hooks/` to `~/.loci/hooks/`, and appends hooks to `~/.claude/settings.json`. It is idempotent — safe to re-run, replaces only its own entries (detected via the `/.loci/hooks/` marker in command strings), and preserves other hooks in the same event slots. `loci uninstall` reverses this, removing only loci entries from both files.

Hook scripts:

- `session_start.py` — runs at session start; fires 3 category-targeted queries (session summaries, manual facts, code) with source filtering, deduplicates, and injects top-5 as `<loci-context>`. Cross-project memories are prefixed with `[ref:project-name]`.
- `post_tool_use.py` — reads `CLAUDE_HOOK_PAYLOAD` env var (JSON with `tool_name`, `tool_input`); fires on Write/Edit/NotebookEdit to store the changed file as a code memory. Skips files under `~/.loci/` to avoid indexing deployed hooks.
- `session_stop.py` — reads `LOCI_SESSION_SUMMARY` env var or stdin; saves each line (>20 chars) as a "session"-tagged memory
- `user_prompt_submit.py` — runs on every user prompt; uses the prompt text as a semantic search query to inject up to 3 relevant memories (2K char budget). Skips trivial prompts (short, slash commands, confirmations like "yes"/"ok"/"lgtm") to avoid unnecessary latency.

### Storage Schema

Single SQLite DB at `~/.loci/memories.db` (overridable via `LOCI_DB_PATH`):
- `memories` table — content, JSON tags, project path, source type, source_ref (file path), chunk_idx, `is_stale` flag
- `memories_fts` — FTS5 virtual table, auto-synced via triggers
- `memories_vec` — sqlite-vec virtual table for ANN (float32[384])
- `project_refs` — directed graph of cross-project references (`src_project -> dst_project`)
- `file_index` — per-file metadata (content_hash, symbols, line_count) for two-tier search
- `file_index_vec` — file-level embeddings for semantic file search
- `_schema_version` — tracks applied migration versions
- `_metadata` — key-value store (currently tracks `embed_model` for version compatibility)

### Cross-Project References

Projects can declare references to other projects via `loci ref add`. When a reference exists, `recall`/`search` automatically surfaces memories from referenced projects alongside local ones. Referenced-project results are weighted by `REF_WEIGHT` (0.7) during RRF fusion so local results rank higher. The reference graph supports BFS traversal up to 2 hops deep (`refs.resolve_projects()`). The session start hook prefixes cross-project memories with `[ref:project-name]` for clarity.

MCP tools: `add_ref`, `remove_ref`, `list_refs`, `index_ref`.

### Key Design Decisions

- **Thread-local connection pool:** `store._connect()` caches one SQLite connection per thread in `threading.local()`, eliminating per-call `sqlite-vec` extension loading overhead (~6.6ms each). Thread-local (not a plain global) because `watchdog` observer threads call store functions concurrently. An `atexit` handler closes connections on exit.
- **Batch insert:** `store.insert_batch()` accepts a list of `ChunkInput` and: (1) embeds all texts in one `embed()` call, (2) fetches all existing vectors and computes a similarity matrix for dedup (falls back to per-chunk ANN if >100K existing vectors), (3) performs intra-batch dedup, (4) inserts all non-duplicate chunks in a single transaction. All ingest callers (`code.py`, `pdf.py`, `docx.py`, `web.py`, `watcher.py`, `cli.py import`) use `insert_batch()`. The original `insert()` is kept for single-item callers (MCP `remember`, CLI `add`, hooks).
- **Deduplication threshold:** score ≥ 0.95 skips storing duplicate chunks (`store.py`). The dedup metric is `1 - L2_distance`, matching `vector_search()` scoring. Per-project dedup uses a stricter 0.99 threshold to reduce false positives within the same project.
- **Project scoping:** memories are keyed to the git repo root (or CWD), so `recall` only returns relevant project context by default. Cross-project references extend this to include referenced projects with a 0.7× RRF weight penalty.
- **Hybrid retrieval:** RRF merges vector and keyword rankings using `1/(rank+60)` — neither alone is used; both contribute. Source boost (manual 1.5×, session 1.3×) and exponential recency decay are applied after RRF. Both `vector_search` and `fts_search` support `source` and `tags` filtering at the SQL level.
- **Embedding model is a singleton:** loaded once in `embedder.py`, shared across the process to avoid reload overhead. Model version is tracked in `_metadata` table; a mismatch warns on stderr and suggests reindexing.
- **File size cap:** files exceeding `MAX_FILE_SIZE` (1MB) are skipped during indexing to avoid wasting time on generated/bundled files.
- **Chunk overlap:** adjacent chunks share 200 characters of overlap (`CHUNK_OVERLAP`) so functions or paragraphs straddling a boundary retain context in both chunks.
- **Incremental indexing:** `ingest_codebase()` compares `st_mtime` against `MAX(created_at)` per file; unchanged files are skipped. `--force` / `force=True` bypasses this and replaces all chunks.
- **Stale/delete pattern:** before reindexing a file, old chunks are marked `is_stale=True`; after new chunks are inserted, stale entries are deleted. This keeps the DB consistent if indexing is interrupted.
- **Directory pruning:** `ingest/code.py` uses `os.walk` (not `rglob`) with in-place `dirnames` pruning. Directories in `config.SKIP_DIRS` (e.g. `node_modules`, `venv`, `__pycache__`, `build`, `dist`) and hidden directories are never descended into, avoiding expensive enumeration of large dependency trees.
- **Gitignore awareness:** `ingest/code.py` uses `pathspec` (gitwildmatch) to match `.gitignore` patterns, supporting directory patterns (`node_modules/`), `**` globs, and negation — unlike the previous `fnmatch` approach which couldn't match directory-style patterns.
- **Idempotent install/uninstall:** `loci install` uses a `/.loci/hooks/` marker in hook command strings to identify its own entries. It strips any existing loci hooks before appending fresh ones, so re-running never duplicates. `loci uninstall` uses the same marker to selectively remove loci entries without touching other hooks.
- **WAL mode + busy_timeout:** Connections use `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` for safe concurrent access (e.g. hooks firing during indexing).
- **Schema migrations:** `loci/migrations/` contains numbered migration files. `init_db()` runs pending migrations via a `_schema_version` table, so schema changes in future releases apply automatically to existing databases.
- **SQLite extension requirement:** `sqlite-vec` needs Python built with `--enable-loadable-sqlite-extensions`. On macOS the system SQLite lacks this, so the install script (`install.sh`) installs Homebrew SQLite and links Python against it. `store.py` raises a clear `RuntimeError` if the capability is missing at runtime.
