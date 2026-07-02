"""Test sync_anki.compute_bands() — auto frequency banding for full-text decks.

Covers:
  - compute_bands() greedy partition algorithm
  - Edge cases: empty, too few words, single level, sparse levels
  - Merging undersized bands
  - Band name formatting
"""

import pytest
import sys
import os

# Ensure sync_anki is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.sync_anki import compute_bands


# ── Edge cases ─────────────────────────────────────────────────────────────

def test_empty_input_returns_none():
    assert compute_bands({}) is None


def test_total_below_min_size_returns_none():
    assert compute_bands({4: 30, 5: 40}, min_band_size=100) is None


def test_single_level_returns_none():
    assert compute_bands({4: 200}) is None


def test_all_none_levels_ignored():
    # If somehow called without filtering, the count dict is empty
    assert compute_bands({}) is None


# ── Basic banding ──────────────────────────────────────────────────────────

def test_even_distribution_two_bands():
    """150 words in level 4 + 150 in level 7 → 2 bands."""
    counts = {4: 150, 7: 150}
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    assert len(bands) == 2
    names = [b[0] for b in bands]
    assert "COCA 4" in names


def test_even_distribution_five_bands():
    """200 words each in 5 distinct levels → 5 bands."""
    counts = {4: 200, 6: 200, 8: 200, 10: 200, 12: 200}
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    assert len(bands) == 5
    # Each band should have roughly equal counts
    for _name, lo, hi in bands:
        band_total = sum(counts[l] for l in range(lo, hi + 1) if l in counts)
        assert band_total >= 100


def test_many_levels_five_bands_max():
    """25 levels with uniform counts → capped at 5 bands."""
    counts = {i: 50 for i in range(1, 26)}
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    assert len(bands) <= 5


# ── Merging undersized bands ───────────────────────────────────────────────

def test_tail_band_merged():
    """Last band below min_size → merged into previous."""
    counts = {4: 150, 7: 150, 10: 30}
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    # Should merge tail (10: 30) into previous band
    assert len(bands) == 2
    # Last band should now cover level 10
    assert bands[-1][2] >= 10  # hi covers level 10


def test_middle_small_band_merged():
    """If a middle band falls below min_size after greedy split,
    post-processing merge handles it."""
    # Level 4: 150, Level 5: 20, Level 7: 150
    # Greedy: target=320/2=160. Band 1: 4 (150, below target, keeps going),
    # adds 5 (20) = 170 >= 160, cut. Band 2: 7 (150).
    # Band 1: (4,5) = 170, Band 2: (7,7) = 150. Both >= 100. OK.
    counts = {4: 150, 5: 20, 7: 150}
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    assert len(bands) == 2


def test_very_small_total_no_bands():
    """Below min_size → None."""
    counts = {4: 30, 5: 20}
    assert compute_bands(counts, min_band_size=100) is None


# ── Sparse levels ──────────────────────────────────────────────────────────

def test_sparse_levels_independent_bands():
    """Levels with gaps form bands that respect both count targets and gaps."""
    counts = {4: 60, 5: 50, 6: 40, 12: 60, 13: 50, 14: 40}
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    assert len(bands) == 2
    # All bands should have >= min_band_size words
    for _name, lo, hi in bands:
        band_total = sum(counts[l] for l in range(lo, hi + 1) if l in counts)
        assert band_total >= 100


# ── Band name formatting ───────────────────────────────────────────────────

def test_single_level_band_name():
    """A band covering a single level uses 'COCA N' format."""
    counts = {4: 200, 7: 200}
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    # Level 4 alone is one band → "COCA 4"
    assert any(b[0] == "COCA 4" for b in bands)
    assert any(b[0] == "COCA 7" for b in bands)


def test_multi_level_band_name():
    """A single contiguous block with K=1 returns None (no sub-decking needed).
    The caller creates a flat deck."""
    counts = {4: 50, 5: 60, 6: 40}
    # total=150, K=min(5, 3, 1)=1 → None
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is None


def test_multi_level_two_bands():
    """Two multi-level bands with enough words produce 'COCA M-N' names."""
    counts = {4: 70, 5: 60, 10: 70, 11: 60}
    # total=260, K=min(5, 4, 2)=2, gap between 5→10 forces natural cut
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    assert len(bands) == 2
    assert bands[0][0] == "COCA 4-5"
    assert bands[1][0] == "COCA 10-11"


# ── K determination ────────────────────────────────────────────────────────

def test_k_capped_by_max_bands():
    """Even with many levels, max_bands caps K."""
    counts = {i: 200 for i in range(1, 26)}  # 25 levels, 200 words each
    bands = compute_bands(counts, max_bands=3, min_band_size=100)
    assert bands is not None
    assert len(bands) <= 3


def test_k_capped_by_total_div_min_size():
    """K cannot exceed total // min_band_size."""
    counts = {4: 80, 5: 70, 7: 60, 10: 50}  # total=260, 260//100=2
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    assert bands is not None
    assert len(bands) <= 2


def test_consecutive_levels_merged_naturally():
    """Dense levels like 4-10 should form contiguous bands."""
    counts = {
        4: 40, 5: 35, 6: 30, 7: 25, 8: 20, 9: 15, 10: 10
    }  # total=175, K=1 since 175//100=1
    bands = compute_bands(counts, max_bands=5, min_band_size=100)
    # total=175, 175//100=1 → K=1 → None (single band)
    assert bands is None
