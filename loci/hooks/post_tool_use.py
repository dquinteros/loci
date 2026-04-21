#!/usr/bin/env python3
"""PostToolUse hook — captures file edits as code memories."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".loci"))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    payload_raw = os.environ.get("CLAUDE_HOOK_PAYLOAD", "")
    if not payload_raw and not sys.stdin.isatty():
        payload_raw = sys.stdin.read()

    if not payload_raw:
        sys.exit(0)

    payload = json.loads(payload_raw)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    # Only react to file-write tools
    if tool_name not in {"Write", "Edit", "NotebookEdit"}:
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        sys.exit(0)

    loci_home = Path.home() / ".loci"
    if path.resolve().is_relative_to(loci_home):
        sys.exit(0)

    from loci import store, config
    from loci.store import init_db
    from loci.ingest import code as code_ingest

    if path.suffix not in config.CODE_EXTENSIONS:
        sys.exit(0)

    init_db()
    project = os.getcwd()
    store.mark_stale(str(path))
    code_ingest.ingest_file(path, project=project)
    store.delete_stale(str(path))
except Exception as exc:
    print(f"[loci] post_tool_use error: {exc}", file=sys.stderr)
