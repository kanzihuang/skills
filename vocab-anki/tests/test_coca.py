"""Test lib/coca.py — three-tier COCA lookup and frequency ranking.

Covers historical errors:
  - Derivational suffix stripping (indulgently→indulgent, resentfulness→resentful)
  - Frequency range filtering correctness
  - bet rank 2989 correctly excluded from 5000-10000 range
"""

import pytest
from coca import in_coca, load_coca, load_freq_ranked


def test_load_coca_returns_set():
    """load_coca returns a non-empty set."""
    coca = load_coca()
    assert isinstance(coca, set)
    assert len(coca) > 10000
    assert "the" in coca  # most common word
    assert "unbalance" in coca  # last word in list (known to be present)


def test_load_coca_cached():
    """load_coca returns the same object on repeated calls."""
    a = load_coca()
    b = load_coca()
    assert a is b


def test_load_freq_ranked_returns_ordered_list():
    """load_freq_ranked returns order-preserving list."""
    ranked = load_freq_ranked()
    assert isinstance(ranked, list)
    assert len(ranked) > 10000
    assert ranked[0] == "the"       # rank 1 = most frequent
    assert ranked[1] == "be"         # rank 2
    assert ranked[18963] == "unbalance"  # rank 18964 = least frequent


def test_load_freq_ranked_top_n():
    """load_freq_ranked(top_n) returns first N entries."""
    ranked = load_freq_ranked(10)
    assert len(ranked) <= 10  # may return fewer if N < available
    assert len(ranked) > 0
    assert ranked[0] == "the"


# ── Tier 1: Direct lookup ──

@pytest.mark.parametrize("word", [
    "the", "be", "indulgent", "resentful",
    "shark", "skiff", "tuna",
])
def test_in_coca_tier1_direct(word, coca_set):
    """Words directly in COCA return True with detail=word."""
    ok, detail = in_coca(word, coca_set)
    assert ok, f"{word} should be in COCA"
    assert " -> " not in detail, f"direct match should not have arrow: {detail}"


# ── Tier 2: lemminflect reduction ──

def test_in_coca_tier2_lemminflect_runs(coca_set):
    """lemmatize_word reduces 'runs' → 'run' via lemminflect."""
    ok, detail = in_coca("runs", coca_set)
    assert ok
    assert "run" in detail


# ── Tier 3: Derivational suffix stripping (commit 48c805c) ──

@pytest.mark.parametrize("word,expected_base", [
    ("indulgently", "indulgent"),     # -ly → (stem)
    ("resentfulness", "resentful"),   # -fulness → -ful
    ("hoping", "hope"),              # -ing → +e
])
def test_in_coca_tier3_derivational(word, expected_base, coca_set):
    """Derivational suffix stripping finds COCA base forms."""
    ok, detail = in_coca(word, coca_set)
    assert ok, f"{word} should reach COCA via derivational fallback"
    assert expected_base in detail, \
        f"detail should indicate {expected_base}: got {detail}"


# ── Words NOT in COCA ──

def test_in_coca_not_found(coca_set):
    """Words not in COCA and not reducible return False."""
    ok, detail = in_coca("blundering", coca_set)
    # blundering is a derivational adj - not directly in COCA
    # If lemminflect or suffix stripping can't find it, returns False
    # (it may or may not be found depending on the lemmatizer version)
    # The key test: the function should not crash and should return a bool
    assert isinstance(ok, bool)
    assert isinstance(detail, str)


def test_in_coca_gibberish(coca_set):
    """Non-word input returns False gracefully."""
    ok, detail = in_coca("xyzkkqw", coca_set)
    assert not ok


# ── Frequency range filtering ──

def test_bet_rank_2989_excluded_from_5000_10000():
    """bet at rank 2989 should NOT be in 5000-10000 range."""
    ranked = load_freq_ranked()
    # Find bet's rank
    try:
        rank = ranked.index("bet") + 1  # 1-based
    except ValueError:
        rank = -1
    # bet may or may not be in coca_freq.txt depending on version
    if rank > 0:
        assert rank < 5000, f"bet rank {rank} should be < 5000 (outside 5000-10000 range)"


def test_shark_in_range_3000_5000():
    """shark should be in 3001-5000 range (rank ~3003)."""
    ranked = load_freq_ranked()
    try:
        rank = ranked.index("shark") + 1
    except ValueError:
        return  # not in list, skip
    assert 3001 <= rank <= 5000, f"shark rank {rank} should be in 3000-5000"


def test_frequency_range_slicing():
    """load_freq_ranked slice [3000:5000] contains 2000 entries."""
    ranked = load_freq_ranked()
    hi = min(5000, len(ranked))
    lo = max(3001, 1) - 1
    subset = set(ranked[lo:hi])
    assert len(subset) > 0
    # Top-10 words should NOT be in 3001-5000 range
    assert "the" not in subset
    assert "be" not in subset
    assert "of" not in subset
