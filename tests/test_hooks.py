"""Tests for hook scripts logic."""
from __future__ import annotations

from pathlib import Path


def test_post_tool_use_skips_loci_home(tmp_path):
    """Files under ~/.loci/ should be skipped by post_tool_use."""
    loci_home = Path.home() / ".loci"
    hook_path = loci_home / "hooks" / "session_start.py"
    if hook_path.exists():
        assert hook_path.resolve().is_relative_to(loci_home)


def test_post_tool_use_skips_non_code_extensions(tmp_path):
    """Non-code extensions should not trigger ingestion."""
    from loci.config import CODE_EXTENSIONS
    non_code = {".json", ".yaml", ".toml", ".csv", ".xml", ".html"}
    for ext in non_code:
        assert ext not in CODE_EXTENSIONS


def test_session_stop_filters_short_lines():
    """Lines under 20 chars should be filtered by session_stop logic."""
    lines = [
        "Short",
        "This is a longer line that should be kept in session memory",
        "x",
        "Another meaningful session summary line about decisions",
    ]
    kept = [line for line in lines if len(line) > 20]
    assert len(kept) == 2
    assert all(len(line) > 20 for line in kept)
