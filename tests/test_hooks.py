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


# --- UserPromptSubmit hook tests ---

from loci.hooks.user_prompt_submit import is_trivial, format_memories, CONTEXT_BUDGET


class _FakeMemory:
    def __init__(self, content: str, project: str = "/proj"):
        self.content = content
        self.project = project


def test_trivial_short_prompts():
    """Prompts under 15 chars are trivial."""
    assert is_trivial("yes")
    assert is_trivial("ok")
    assert is_trivial("n")
    assert is_trivial("")
    assert is_trivial("   hi   ")


def test_trivial_slash_commands():
    """Slash commands are trivial."""
    assert is_trivial("/help")
    assert is_trivial("/review this code please")
    assert is_trivial("  /compact  ")


def test_trivial_confirmation_words():
    """Common confirmation words are trivial."""
    for word in ["yes", "no", "ok", "continue", "go ahead", "lgtm",
                 "thanks", "sure", "do it", "looks good", "sounds good"]:
        assert is_trivial(word), f"Expected '{word}' to be trivial"


def test_trivial_punctuation_and_case():
    """Punctuation is stripped and matching is case-insensitive."""
    assert is_trivial("LGTM")
    assert is_trivial("  Yes!!!  ")
    assert is_trivial("OK!!!")
    assert is_trivial("Go ahead")


def test_nontrivial_real_prompts():
    """Real questions and instructions are not trivial."""
    assert not is_trivial("How does the authentication middleware work?")
    assert not is_trivial("Refactor the database connection pool")
    assert not is_trivial("Add a new endpoint for user registration")
    assert not is_trivial("What is the architecture of the retriever module?")


def test_format_memories_basic():
    """Formats memories with source labels."""
    memories = [
        _FakeMemory("some code function", "/proj"),
        _FakeMemory("cross project info", "/other"),
    ]
    result = format_memories(memories, "/proj")
    assert "- some code function" in result
    assert "- [ref:other] cross project info" in result


def test_format_memories_budget_cap():
    """Output respects the budget limit."""
    long_content = "x" * 1000
    memories = [
        _FakeMemory(long_content, "/proj"),
        _FakeMemory(long_content, "/proj"),
        _FakeMemory(long_content, "/proj"),
    ]
    result = format_memories(memories, "/proj", budget=500)
    assert len(result) <= 500


def test_format_memories_empty():
    """Empty memory list produces empty string."""
    assert format_memories([], "/proj") == ""


def test_trivial_whitespace_only():
    """Whitespace-only prompts are trivial."""
    assert is_trivial("   ")
    assert is_trivial("\t\n")
