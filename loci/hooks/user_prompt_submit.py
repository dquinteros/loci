#!/usr/bin/env python3
"""Injected on every user prompt — searches memories relevant to the prompt."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".loci"))
sys.path.insert(0, str(Path(__file__).parent.parent))

TRIVIAL_PATTERNS = frozenset({
    "yes", "no", "ok", "okay", "continue", "go ahead", "y", "n",
    "lgtm", "thanks", "thank you", "sure", "do it", "looks good",
    "sounds good", "got it", "perfect", "great", "nice", "cool",
    "agreed", "correct", "right", "yep", "nope", "done",
})

CONTEXT_BUDGET = 2000


def is_trivial(prompt: str) -> bool:
    stripped = prompt.strip()
    if len(stripped) < 15:
        return True
    if stripped.startswith("/"):
        return True
    normalized = re.sub(r"[^\w\s]", "", stripped).lower().strip()
    return normalized in TRIVIAL_PATTERNS


def format_memories(memories: list, project: str, budget: int = CONTEXT_BUDGET) -> str:
    lines: list[str] = []
    total = 0
    for m in memories:
        label = f"[ref:{Path(m.project).name}] " if m.project != project else ""
        line = f"- {label}{m.content}"
        if total + len(line) > budget:
            remaining = budget - total
            if remaining > 40:
                lines.append(line[:remaining])
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


try:
    payload = json.loads(sys.stdin.read())
    prompt = payload.get("prompt", "")

    if is_trivial(prompt):
        sys.exit(0)

    from loci import retriever, store
    from loci.store import init_db

    init_db()
    project = os.getcwd()

    memories = retriever.hybrid_search(prompt, k=3, project=project)

    if memories:
        formatted = format_memories(memories, project)
        if formatted:
            print("<loci-context>")
            print(formatted)
            print("</loci-context>")
except Exception as exc:
    print(f"[loci] user_prompt_submit error: {exc}", file=sys.stderr)
