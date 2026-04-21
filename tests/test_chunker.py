"""Tests for the chunker module."""
from __future__ import annotations

from loci.chunker import chunk


def test_empty_input_returns_empty():
    assert chunk("") == []
    assert chunk("   ") == []
    assert chunk(None) == []  # type: ignore[arg-type]


def test_small_text_returns_single_chunk():
    text = "Hello world"
    result = chunk(text, size=100)
    assert result == ["Hello world"]


def test_splits_on_paragraph_boundary():
    text = "First paragraph.\n\nSecond paragraph."
    result = chunk(text, size=25, overlap=0)
    assert len(result) == 2
    assert "First" in result[0]
    assert "Second" in result[1]


def test_overlap_produces_shared_content():
    text = "AAAA\n\nBBBB\n\nCCCC\n\nDDDD"
    result = chunk(text, size=10, overlap=4)
    assert len(result) >= 2
    if len(result) >= 2:
        tail_of_first = result[0][-4:]
        assert tail_of_first in result[1]


def test_character_fallback_with_no_separator():
    text = "a" * 100
    result = chunk(text, size=30, overlap=0)
    assert len(result) >= 3
    assert all(len(c) <= 30 for c in result)


def test_overlap_character_fallback():
    text = "a" * 100
    result = chunk(text, size=30, overlap=10)
    total_chunks = len(result)
    assert total_chunks >= 4
