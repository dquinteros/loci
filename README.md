```
 ██╗      ██████╗  ██████╗██╗
 ██║     ██╔═══██╗██╔════╝██║
 ██║     ██║   ██║██║     ██║
 ██║     ██║   ██║██║     ██║
 ███████╗╚██████╔╝╚██████╗██║
 ╚══════╝ ╚═════╝  ╚═════╝╚═╝
```

> **Local RAG memory for Claude Code.** Loci gives Claude persistent, searchable memory of your projects — code, documents, and sessions — stored entirely on your machine.

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

---

## Installation

```bash
curl -sSL https://raw.githubusercontent.com/dquinteros/loci/main/install.sh | bash
```

The script detects Python 3.10+, installs it via pyenv if missing, then registers loci as an MCP server and hooks with Claude Code.

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

This walks the directory, chunks all source files (`.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, `.tsx`, `.jsx`, `.rb`, `.cpp`, `.c`, `.h`), and stores them with vector embeddings. Duplicates (cosine similarity ≥ 0.95) are skipped automatically.

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
| `recall(query, k)` | Retrieve the most relevant memories |
| `forget(id)` | Delete a memory by ID |
| `list_memories(tag, limit)` | List project memories, optionally filtered by tag |
| `index_codebase(force)` | Index (or incrementally update) the current project codebase |

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
| Chunk size | 1024 characters |
| Default results (`-k`) | 5 |
| Dedup threshold | cosine similarity ≥ 0.95 |
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

## License

MIT
