#!/usr/bin/env python3
"""Injected at session start — prints relevant project memories as context."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".loci"))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from loci import retriever, store
    from loci.store import init_db

    init_db()
    project = os.getcwd()
    memories = retriever.hybrid_search(
        "project context conventions important facts", k=5, project=project
    )
    if memories:
        print("<loci-context>")
        for m in memories:
            label = f"[ref:{Path(m.project).name}] " if m.project != project else ""
            print(f"- {label}{m.content}")
        print("</loci-context>")
except Exception as exc:
    print(f"[loci] session_start error: {exc}", file=sys.stderr)
