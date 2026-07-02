"""Test lib/coca.py — Nation BNC/COCA word family lookup.

Covers:
  - Level-based frequency filtering (replaces corrupted rank-based COCA data)
  - get_word_level() — word form → level (1-25)
  - get_word_headword() — word form → family headword
  - load_level_range() — all word forms in a level range
  - in_coca() — three-tier lookup (unchanged API, new Nation data backing)
  - Three-layer protection model: Nation catches inter-family errors,
    Claude override + spaCy POS gate catch intra-family over-reductions.
"""

import pytest
from lib.coca import (in_coca, load_coca, load_freq_ranked,
                   get_word_level, get_word_headword, load_level_range)


# ── Data loading ──────────────────────────────────────────────────────────

def test_load_coca_returns_set():
    """load_coca returns a non-empty set with known common words."""
    coca = load_coca()
    assert isinstance(coca, set)
    assert len(coca) > 50000  # Nation 25 levels have ~77K word forms
    assert "the" in coca       # level 1
    assert "twined" in coca    # level 6, family member
    assert "blundering" in coca  # level 7, family member


def test_load_coca_cached():
    """load_coca returns the same object on repeated calls."""
    a = load_coca()
    b = load_coca()
    assert a is b


def test_load_freq_ranked_returns_headwords():
    """load_freq_ranked returns headwords in level order."""
    ranked = load_freq_ranked()
    assert isinstance(ranked, list)
    assert len(ranked) > 20000  # ~25K headwords
    # First entries are level 1, alphabetically sorted within level
    # (HUNGRY is alphabetically first in basewrd1.txt)
    assert len(ranked[0]) > 0


def test_load_freq_ranked_top_n():
    """load_freq_ranked(top_n) returns first N entries."""
    ranked = load_freq_ranked(100)
    assert len(ranked) <= 100
    assert len(ranked) > 0


# ── get_word_level ────────────────────────────────────────────────────────

@pytest.mark.parametrize("word, expected_level", [
    ("the", 1),
    ("be", 1),
    ("and", 1),
    ("twined", 6),     # family member under TWINE (level 6)
    ("twin", 2),       # headword TWIN (level 2)
    ("blundering", 7), # family member under BLUNDER (level 7)
    ("blunder", 7),    # headword BLUNDER (level 7)
])
def test_get_word_level(word, expected_level):
    """Known words return the correct BNC/COCA level."""
    assert get_word_level(word) == expected_level


def test_get_word_level_unknown():
    """Unknown word returns None."""
    assert get_word_level("xyzkkqw") is None
    assert get_word_level("") is None


# ── get_word_headword ─────────────────────────────────────────────────────

def test_get_word_headword_member():
    """Family member returns its headword."""
    assert get_word_headword("twined") == "twine"
    assert get_word_headword("blundering") == "blunder"
    assert get_word_headword("conceited") == "conceit"


def test_get_word_headword_headword():
    """Headword returns itself."""
    assert get_word_headword("twine") == "twine"
    assert get_word_headword("twin") == "twin"
    assert get_word_headword("blunder") == "blunder"


def test_get_word_headword_unknown():
    """Unknown word returns None."""
    assert get_word_headword("xyzkkqw") is None


# ── load_level_range ──────────────────────────────────────────────────────

def test_load_level_range_basic():
    """Level 1 contains common words, level 25 contains rare words."""
    l1 = load_level_range(1, 1)
    assert "the" in l1
    assert "be" in l1
    assert len(l1) > 1000

    # Level 25 should have rare words
    high = load_level_range(25, 25)
    assert len(high) > 0


def test_load_level_range_exclusion():
    """Levels 11-25 should NOT contain level 1 words."""
    high = load_level_range(11, 25)
    assert "the" not in high
    assert "be" not in high
    assert "and" not in high


def test_load_level_range_bounds():
    """Bounds are clamped to 1-25."""
    assert len(load_level_range(0, 5)) > 0   # lo clamped to 1
    assert len(load_level_range(1, 30)) > 0  # hi clamped to 25
    assert load_level_range(10, 5) == set()  # lo > hi → empty


# ── in_coca: Tier 1 (direct lookup) ───────────────────────────────────────

@pytest.mark.parametrize("word", [
    "the", "be", "indulgent", "resentful", "twine", "blunder",
])
def test_in_coca_tier1_direct(word, coca_set):
    """Words directly in Nation lists return True with detail=word."""
    ok, detail = in_coca(word, coca_set)
    assert ok, f"{word} should be in Nation lists"
    assert " -> " not in detail, f"direct match should not have arrow: {detail}"


# ── in_coca: Tier 2 (lemminflect reduction) ───────────────────────────────

def test_in_coca_tier2_lemminflect_runs(coca_set):
    """lemmatize_word reduces 'runs' → 'run' via lemminflect."""
    ok, detail = in_coca("runs", coca_set)
    assert ok
    assert "run" in detail


# ── in_coca: Tier 3 (derivational suffix stripping) ───────────────────────

@pytest.mark.parametrize("word,expected_base", [
    ("indulgently", "indulgent"),     # -ly → (stem)
    ("resentfulness", "resentful"),   # -fulness → -ful
])
def test_in_coca_tier3_derivational(word, expected_base, coca_set):
    """Derivational suffix stripping finds Nation base forms."""
    ok, detail = in_coca(word, coca_set)
    assert ok, f"{word} should reach Nation via derivational fallback"
    assert expected_base in detail


# ── in_coca: Not found ────────────────────────────────────────────────────

def test_in_coca_not_found(coca_set):
    """Gibberish returns False."""
    ok, detail = in_coca("xyzkkqw", coca_set)
    assert not ok


def test_in_coca_empty(coca_set):
    """Empty string returns False."""
    ok, detail = in_coca("", coca_set)
    assert not ok


# ── Three-layer protection verification ───────────────────────────────────

def test_twined_twin_different_families():
    """twined (TWINE family) and twin (TWIN family) are different families.

    This is the core inter-family case the Nation validation layer catches.
    lemminflect may return 'twin' for 'twined' — but Nation says they belong
    to different word families.
    """
    assert get_word_headword("twined") == "twine"
    assert get_word_headword("twin") == "twin"
    assert get_word_headword("twined") != get_word_headword("twin")


def test_blundering_blunder_same_family():
    """blundering and blunder are in the SAME family (BLUNDER).

    Nation Level 6 intentionally groups derivational adjectives with their
    roots.  This is NOT an error — the Claude override + spaCy POS gate
    layers handle intra-family protection.
    """
    assert get_word_headword("blundering") == "blunder"
    assert get_word_headword("blunder") == "blunder"
    assert get_word_headword("blundering") == get_word_headword("blunder")
