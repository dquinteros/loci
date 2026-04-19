#!/usr/bin/env python3
"""Saves key facts from the session summary when Claude Code stops."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".loci"))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from loci import store
    from loci.store import init_db

    init_db()
    summary = os.environ.get("LOCI_SESSION_SUMMARY", "")
    if not summary:
        # Try reading from stdin (Claude Code may pipe it)
        if not sys.stdin.isatty():
            summary = sys.stdin.read()

    project = os.getcwd()
    count = 0
    for line in summary.strip().splitlines():
        line = line.strip()
        if len(line) > 20:
            mem_id = store.insert(line, tags=["session"], project=project, source="session")
            if mem_id:
                count += 1
    if count:
        print(f"[loci] saved {count} session memories", file=sys.stderr)
except Exception as exc:
    print(f"[loci] session_stop error: {exc}", file=sys.stderr)
