```
 ██╗      ██████╗  ██████╗██╗
 ██║     ██╔═══██╗██╔════╝██║
 ██║     ██║   ██║██║     ██║
 ██║     ██║   ██║██║     ██║
 ███████╗╚██████╔╝╚██████╗██║
 ╚══════╝ ╚═════╝  ╚═════╝╚═╝
```

> **Lo**cal **C**ontext **I**ntelligence for Claude Code. Loci gives Claude persistent, searchable memory of your projects — code, documents, and sessions — stored entirely on your machine.

---

## How it works

Every session, loci automatically:

1. **Injects context** — top memories relevant to your project are surfaced at session start
2. **Captures edits** — file changes made by Claude are stored as code memories in real time
3. **Saves summaries** — a summary of what was done is written when the session ends

Memory lives in a local SQLite database (`~/.loci/memories.db`) and never leaves your machine. Search uses a hybrid of vector embeddings and full-text search (reciprocal rank fusion) so results are fast and relevant.

---

## Requirements

- [Claude Code](https://claude.ai/code) CLI installed
- Python 3.10+ **with SQLite loadable-extension support** (the install script handles this automatically; see [Troubleshooting](#troubleshooting) if you hit issues)

---

## Installation

```bash
curl -sSL https://raw.githubusercontent.com/dquinteros/loci/main/install.sh | bash
```

The script detects Python 3.10+, installs it via pyenv if missing (with SQLite extension support enabled), then registers loci as an MCP server and hooks with Claude Code. If an existing Python lacks extension support, the script rebuilds it automatically.

Restart Claude Code after installing.

`loci install` writes to `~/.claude/settings.json` — it registers:
- An MCP server (`loci serve`) so Claude can call memory tools directly
- Three hooks: `SessionStart`, `PostToolUse`, and `Stop`

Restart Claude Code after installing.

---

## Indexing your codebase

Before loci has anything to recall, point it at your project:

```bash
cd ~/your-project
loci index
```

This walks the directory, chunks all source files (`.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, `.tsx`, `.jsx`, `.rb`, `.cpp`, `.c`, `.h`), and stores them with vector embeddings. Duplicates (similarity score ≥ 0.95) are skipped automatically. Files larger than 1 MB are skipped to avoid indexing generated bundles.

**Incremental indexing** — by default, `loci index` skips files whose modification time hasn't changed since they were last indexed. Re-runs are fast and safe to call frequently. Use `--force` to reindex everything:

```bash
loci index          # only changed files (default)
loci index --force  # reindex all files unconditionally
```

---

## CLI Reference

### Add memories manually

```bash
# Store a plain text memory
loci add "the auth middleware expects a Bearer token in the Authorization header"

# Tag it for easier filtering later
loci add "deploy target is fly.io, region ord" --tag deployment --tag infra
```

### Ingest documents

```bash
# PDF, DOCX, Markdown, or plain text
loci add-doc docs/architecture.pdf --tag architecture
loci add-doc CHANGELOG.md --tag changelog

# Any web URL
loci add-doc https://docs.example.com/api --tag reference
```

### Search

```bash
# Hybrid vector + keyword search
loci search "authentication flow"

# Return more results
loci search "database migrations" -k 10
```

Example output:
```
[code] 'def authenticate(token: str) -> User:\n    payload = jwt.decode(token, SECRET...'
  tags: ['code']  id: a3f2c1d8
[manual] 'the auth middleware expects a Bearer token in the Authorization header'
  tags: ['deployment']  id: b91e4a02
```

### List and inspect

```bash
# All memories for the current project
loci list

# Filter by tag
loci list --tag session

# Show more
loci list --limit 50
```

### Watch a folder

```bash
# Auto-ingest files dropped into ~/loci-docs/
loci watch
```

Drop PDFs, docs, or markdown into `~/loci-docs/` and loci picks them up automatically.

### Cross-project references

Link related projects so memories from one are surfaced when working in another:

```bash
# Declare a reference to another project
loci ref add ../shared-lib

# Index the referenced project's codebase (also adds the ref if missing)
loci index-ref ../shared-lib
loci index-ref ../shared-lib --force   # full reindex

# List all references from the current project
loci ref list

# Remove a reference
loci ref remove ../shared-lib
```

Once a reference exists, `loci search` and Claude's `recall` automatically include memories from referenced projects (weighted slightly lower so local results rank first). References are traversed up to 2 hops deep — if project A references B and B references C, searching in A also surfaces C's memories.

### Uninstall

```bash
loci uninstall
```

Removes the loci MCP server from `~/.claude.json` and all loci hooks from `~/.claude/settings.json`. Other MCP servers and hooks are left untouched.

### Export and import

```bash
# Print the DB path (useful for backups)
loci export

# Export all memories as JSON
loci export --json > memories.json

# Merge memories from another DB
loci import /path/to/other/memories.db
```

---

## MCP Tools (used by Claude directly)

When Claude Code is connected via MCP, these tools are available in any conversation:

| Tool | Description |
|------|-------------|
| `remember(content, tags, project)` | Store a fact or note |
| `recall(query, k, source, tags)` | Retrieve the most relevant memories (optionally filter by source type or tags) |
| `forget(id)` | Delete a memory by ID |
| `list_memories(tag, limit)` | List project memories, optionally filtered by tag |
| `index_codebase(force)` | Index (or incrementally update) the current project codebase |
| `find_files(query, k)` | Find project files by name or symbol via semantic search |
| `add_ref(path)` | Add a cross-project reference |
| `remove_ref(path)` | Remove a cross-project reference |
| `list_refs()` | List all references from the current project |
| `index_ref(path, force)` | Index a referenced project's codebase |

Claude uses `recall` and `remember` automatically — you don't need to ask it to. You can also ask Claude to run `index_codebase` mid-session to pick up new files without leaving the conversation.

---

## Configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `LOCI_DB_PATH` | `~/.loci/memories.db` | Custom path for the SQLite database |

Defaults set in `loci/config.py`:

| Setting | Value |
|---------|-------|
| Embedding model | `BAAI/bge-small-en-v1.5` (384-dim, runs locally) |
| Chunk size | 1024 characters (2048 for code), 200-char overlap |
| Max file size | 1 MB (larger files skipped during indexing) |
| Default results (`-k`) | 5 |
| Dedup threshold | score ≥ 0.95 (global), ≥ 0.99 (same project) |
| Source boost | manual 1.5×, session 1.3×, others 1.0× |
| Watch folder | `~/loci-docs` |

---

## Architecture overview

```
Claude Code session
       │
       ├── SessionStart hook ──► inject top-5 relevant memories as <loci-context>
       ├── PostToolUse hook  ──► store edited files as code memories
       └── Stop hook         ──► save session summary as memories
       │
       └── MCP tools (remember / recall / forget / list_memories)
                  │
           loci/retriever.py  ← hybrid search (vector ANN + FTS5, merged via RRF)
                  │
           loci/store.py      ← SQLite + sqlite-vec + FTS5 virtual tables
                  │
           ~/.loci/memories.db
```

---

## Troubleshooting

### `AttributeError: 'sqlite3.Connection' object has no attribute 'enable_load_extension'`

This means your Python was compiled without SQLite loadable-extension support. loci needs this for `sqlite-vec`.

On **macOS**, the system SQLite doesn't support loadable extensions — you need Homebrew's SQLite. If you use pyenv, rebuild Python against it:

```bash
brew install sqlite
PYTHON_CONFIGURE_OPTS="--enable-loadable-sqlite-extensions" \
  LDFLAGS="-L$(brew --prefix sqlite)/lib" \
  CPPFLAGS="-I$(brew --prefix sqlite)/include" \
  pyenv install --force 3.10.16
```

Then reinstall loci:

```bash
pip install -e .   # or: pip install git+https://github.com/dquinteros/loci.git
loci install
```

The install script (`install.sh`) detects this automatically — it installs Homebrew SQLite and rebuilds Python if needed, so re-running the one-liner also works:

```bash
curl -sSL https://raw.githubusercontent.com/dquinteros/loci/main/install.sh | bash
```

---

## License

MIT
