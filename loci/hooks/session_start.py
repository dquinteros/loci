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

    categories = [
        {"query": "session summary decisions progress", "k": 3, "source": "session"},
        {"query": "project architecture conventions facts", "k": 3, "source": "manual"},
        {"query": "important functions main components", "k": 3, "source": "code"},
    ]

    seen_ids: set[str] = set()
    memories: list[store.Memory] = []
    for cat in categories:
        hits = retriever.hybrid_search(
            cat["query"], k=cat["k"], project=project,
            source=cat["source"],
        )
        for m in hits:
            if m.id not in seen_ids:
                seen_ids.add(m.id)
                memories.append(m)

    memories = memories[:5]

    if memories:
        print("<loci-context>")
        for m in memories:
            label = f"[ref:{Path(m.project).name}] " if m.project != project else ""
            print(f"- {label}{m.content}")
        print("</loci-context>")
except Exception as exc:
    print(f"[loci] session_start error: {exc}", file=sys.stderr)
