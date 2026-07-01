"""Test filter_fulltext.py — chapter range parsing and chapter detection.

Covers historical errors:
  - Chapter range parsing edge cases
  - Inverted range detection
  - Unmatched chapter title handling
"""

import pytest
from filter_fulltext import parse_chapter_range, find_chapter_offsets


@pytest.mark.parametrize("range_str,n_chapters,expected", [
    # ── Simple range ──
    ("1-5", 10, {1, 2, 3, 4, 5}),
    ("3-7", 10, {3, 4, 5, 6, 7}),
    # ── Single chapter ──
    ("1", 5, {1}),
    ("5", 10, {5}),
    # ── Comma-separated list ──
    ("1,3,5", 10, {1, 3, 5}),
    ("1-3,5,7-9", 10, {1, 2, 3, 5, 7, 8, 9}),
    # ── Full range ──
    ("1-10", 10, set(range(1, 11))),
    # ── Empty/whitespace → all chapters ──
    ("", 5, {1, 2, 3, 4, 5}),
    ("  ", 5, {1, 2, 3, 4, 5}),
    # ── Single edge ──
    ("1-1", 5, {1}),
    ("5-5", 5, {5}),
])
def test_parse_chapter_range_valid(range_str, n_chapters, expected):
    result = parse_chapter_range(range_str, n_chapters)
    assert result == expected, \
        f"parse_chapter_range({range_str!r}, {n_chapters}) = {result!r}"


@pytest.mark.parametrize("range_str,n_chapters", [
    # ── Out of bounds ──
    ("0-5", 10),         # lo < 1
    ("1-11", 10),        # hi > n_chapters
    ("11", 10),          # single out of bounds
    ("-1", 5),
    # ── Inverted range ──
    ("5-1", 10),         # reversed
    ("7-3", 10),
    # ── Malformed ──
    ("abc", 5),
    ("1-x", 5),
])
def test_parse_chapter_range_invalid(range_str, n_chapters):
    with pytest.raises(ValueError):
        parse_chapter_range(range_str, n_chapters)


def test_find_chapter_offsets_exact_match():
    """Chapter title found by exact match."""
    text = "Chapter One\nOnce upon a time... Chapter Two\nThe next day..."
    titles = [
        {"chapterUid": 1, "title": "Chapter One"},
        {"chapterUid": 2, "title": "Chapter Two"},
    ]
    results = find_chapter_offsets(text, titles)
    assert len(results) == 2
    assert results[0]["offset"] >= 0
    assert results[1]["offset"] >= 0
    assert results[0]["offset"] < results[1]["offset"]


def test_find_chapter_offsets_case_insensitive():
    """Chapter title found by case-insensitive match."""
    text = "CHAPTER ONE\nContent here."
    titles = [{"chapterUid": 1, "title": "Chapter One"}]
    results = find_chapter_offsets(text, titles)
    assert results[0]["offset"] >= 0


def test_find_chapter_offsets_not_found():
    """Unmatched chapter title returns offset -1."""
    text = "Some random text without any chapter markers."
    titles = [{"chapterUid": 1, "title": "Chapter One"}]
    results = find_chapter_offsets(text, titles)
    assert results[0]["offset"] == -1


def test_find_chapter_offsets_empty_titles():
    """Empty titles list returns empty results."""
    results = find_chapter_offsets("any text", [])
    assert results == []
