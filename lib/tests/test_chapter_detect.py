"""Tests for lib/chapter_detect.py — shared chapter-boundary detection."""

from __future__ import annotations

import pytest

# Import the module under test (path is set up by pytest conftest / sys.path)
from lib.chapter_detect import detect_story_start, find_chapter_boundaries


# ── detect_story_start — explicit chapter headings ──────────────────────

@pytest.mark.parametrize("heading,expected_offset", [
    ("CHAPTER I", 0),
    ("Chapter 1", 0),
    ("CHAPTER ONE", 0),
    ("CHAP. 1", 0),
])
def test_detect_chapter_heading_at_start(heading, expected_offset):
    """Chapter heading at position 0 — no preamble, return 0."""
    text = f"{heading}\n\nOnce upon a time there was a little prince who lived on a planet."
    assert detect_story_start(text) == expected_offset


def test_detect_chapter_heading_after_preamble():
    """Preamble before 'Chapter 1' heading — return preamble offset."""
    text = (
        "THE BOOK TITLE\n\n"
        "By Author Name\n\n\n"
        "Chapter 1\n\n"
        "Once upon a time there was a story."
    )
    offset = detect_story_start(text)
    assert offset > 0
    # Body should start with "Chapter 1"
    assert "Chapter 1" in text[offset:]


def test_detect_part_heading():
    text = "Preamble text here.\n\nPART ONE\n\nThe story begins."
    offset = detect_story_start(text)
    assert offset > 0
    assert "PART ONE" in text[offset:]


def test_detect_book_heading():
    text = "Preamble.\n\nBook I\n\nChapter 1 starts here."
    offset = detect_story_start(text)
    assert offset > 0


def test_detect_roman_numeral_heading():
    text = "Front matter.\n\nI.\n\nThe first chapter begins here with narrative text that goes on long enough."
    offset = detect_story_start(text)
    assert offset > 0


def test_no_heading_returns_zero():
    """Text with no chapter heading patterns — safe fallback."""
    text = "Once upon a time there was a story with no chapter headings at all."
    # No chapter heading, no obvious preamble → 0
    assert detect_story_start(text) == 0


def test_part_way_not_a_chapter_heading():
    """'part way' in body text must not match PART\s+[A-Z]+ (regression test).

    re.IGNORECASE made [A-Z]+ match lowercase 'way', causing a false positive
    at offset 95855 in The Old Man and the Sea.  (?-i:[A-Z]+) fixes this.
    """
    text = "the fish pulled\npart way over and then righted himself and swam away."
    assert detect_story_start(text) == 0


def test_part_one_still_detected():
    """'PART ONE' (all caps) must still match after (?-i:) fix."""
    text = "Preamble.\n\nPART ONE\n\nThe story begins here with narrative prose."
    offset = detect_story_start(text)
    assert offset > 0
    assert "PART ONE" in text[offset:]


# ── detect_story_start — fallback heuristic ─────────────────────────────

def test_fallback_skips_title_and_author():
    """All-caps title + author name → skipped as preamble."""
    text = (
        "THE LITTLE PRINCE\n\n\n\n"
        "Antoine De Saint-Exupery\n\n\n\n\n"
        "Once when I was six years old I saw a magnificent picture in a book, "
        "called True Stories from Nature, about the primeval forest."
    )
    offset = detect_story_start(text)
    assert offset > 0
    assert "Once when I was six" in text[offset:]


def test_fallback_skips_author_bio():
    """Author bio with 'who was a' → skipped."""
    text = (
        "THE BOOK\n\n"
        "Author Name, who was a French author, journalist and pilot wrote\n"
        "The Book in 1943, one year before his death.\n\n"
        "Chapter one begins here with the actual narrative that goes on for a "
        "while and describes what happened next in great detail."
    )
    offset = detect_story_start(text)
    assert offset > 0
    assert "Chapter one begins" in text[offset:]


def test_fallback_skips_bio_continuation_and_meta_intro():
    """Bio continuation + literary-analysis intro → both skipped as preamble.

    Regression test: bio continuation (line after BIO match, same paragraph)
    and meta intro lines ("appears to be", "is actually") must be skipped.
    """
    # Narrative must be long enough so preamble < 40% of total
    narrative = (
        "Once when I was six years old I saw a magnificent picture in a book, "
        "called True Stories from Nature, about the primeval forest. "
        "It was a picture of a boa constrictor in the act of swallowing an animal. "
        "Here is a copy of the drawing. In the book it said: "
        '"Boa constrictors swallow their prey whole, without chewing it. '
        'After that they are not able to move, and they sleep through the six months '
        'that they need for digestion." I pondered deeply, then, over the adventures '
        "of the jungle. And after some work with a colored pencil I succeeded in "
        "making my first drawing. My Drawing Number One. It looked something like "
        "this: a boa constrictor digesting an elephant. I showed my masterpiece to "
        "the grown-ups and asked them whether the drawing frightened them."
    )
    text = (
        "THE LITTLE PRINCE\n\n\n\n"
        "Antoine De Saint-Exupery\n\n\n\n\n"
        "Antoine de Saint-Exupery, who was a French author, journalist and pilot wrote\n"
        "The Little Prince in 1943, one year before his death.\n\n"
        "The Little Prince appears to be a simple children's tale,\n"
        "some would say that it is actually a profound and deeply moving tale,\n"
        "written in riddles and laced with philosophy and poetic metaphor.\n\n\n\n\n"
        + narrative
    )
    offset = detect_story_start(text)
    assert offset > 0
    assert "Once when I was six" in text[offset:]


def test_fallback_no_preamble():
    """Plain narrative text — no preamble detected."""
    text = (
        "Once when I was six years old I saw a magnificent picture in a book "
        "about the primeval forest. It was a picture of a boa constrictor."
    )
    assert detect_story_start(text) == 0


def test_fallback_preamble_too_large_rejected():
    """If preamble would be >40% of text, reject to avoid false positives."""
    short_story = "A short story.\n" * 5
    long_preamble = "TITLE PAGE\n\n" * 50
    text = long_preamble + short_story
    # Preamble would be majority of text → reject (return 0)
    assert detect_story_start(text) == 0


# ── find_chapter_boundaries ─────────────────────────────────────────────

def test_find_boundaries_single_chapter():
    text = "Preamble.\n\nCHAPTER I\n\nThe only chapter.\nMore text here."
    bounds = find_chapter_boundaries(text)
    assert len(bounds) == 1
    assert bounds[0]["label"] == "CHAPTER I"
    assert bounds[0]["start"] > 0
    assert bounds[0]["end"] == len(text)


def test_find_boundaries_multiple_chapters():
    text = (
        "CHAPTER I\n\nFirst chapter text here with enough content to matter.\n\n"
        "CHAPTER II\n\nSecond chapter text here also with sufficient content.\n\n"
        "CHAPTER III\n\nThird and final chapter text goes here as well."
    )
    bounds = find_chapter_boundaries(text)
    assert len(bounds) == 3
    assert bounds[0]["label"] == "CHAPTER I"
    assert bounds[1]["label"] == "CHAPTER II"
    assert bounds[2]["label"] == "CHAPTER III"
    # Boundaries should be contiguous
    assert bounds[0]["end"] == bounds[1]["start"]
    assert bounds[1]["end"] == bounds[2]["start"]
    assert bounds[2]["end"] == len(text)


def test_find_boundaries_no_headings():
    text = "Just a plain story with no chapter headings anywhere in sight."
    bounds = find_chapter_boundaries(text)
    assert bounds == []


def test_find_boundaries_chapter_one():
    text = "Preamble.\n\nChapter One\n\nFirst chapter.\n\nChapter Two\n\nSecond."
    bounds = find_chapter_boundaries(text)
    assert len(bounds) == 2
    assert "One" in bounds[0]["label"]
    assert "Two" in bounds[1]["label"]
