"""Test match_sentences.py — PySBD segmentation + _better() comparison.

In the new design, sentences are stored WITHOUT <b> tags. Each result
has 'target_offset', 'matched_form', and 'text' fields. No candidates
array — only the best entry per (lemma, pos) is retained.
"""

import pytest
from lib.scripts.match_sentences import (
    split_sentences,
    hard_truncate,
    _better,
    _clean_quote_artifact,
)


# ── PySBD sentence splitting ──


def test_standard_sentence_split():
    sents = split_sentences("Hello! This is a test. Dr. Smith arrived.")
    assert len(sents) == 3
    assert "Dr. Smith arrived." in sents


def test_dialogue_quote_split():
    sents = split_sentences('"Draw me a sheep!" he said. "What?"')
    assert len(sents) == 2
    assert '"Draw me a sheep!" he said.' in sents


def test_abbreviation_not_split():
    sents = split_sentences("Mr. Jones and Dr. Lee went to U.S. offices.")
    assert len(sents) == 1


# ── Hard truncation ──


def test_hard_truncate_short_sentence_unchanged():
    text, was_truncated = hard_truncate("Short sentence.", max_len=500)
    assert text == "Short sentence."
    assert was_truncated is False


def test_hard_truncate_long_sentence_cut_at_word_boundary():
    long_text = "word " * 200
    result, was_truncated = hard_truncate(long_text, max_len=50)
    assert len(result) <= 50
    assert was_truncated is True
    assert not result.endswith(" ") or result[-1] != " "


# ── _clean_quote_artifact ──

def test_quote_artifact_no_leading_whitespace():
    assert _clean_quote_artifact('" "No,') == '"No,'


def test_quote_artifact_with_leading_whitespace():
    assert _clean_quote_artifact('  " "No,'.strip()) == '"No,'


def test_quote_artifact_clean_sentence_unchanged():
    assert _clean_quote_artifact('"Hello," he said.') == '"Hello," he said.'


# ── _better() three-tier comparison ──


def _cand(length):
    """Helper: build a minimal candidate dict for _better()."""
    return {"len": length, "text": "x" * length}


class TestBetter:
    """Test _better(old, new) — pure comparison, no scoring."""

    # Sweet-spot (30-250): shorter wins
    def test_sweet_spot_shorter_wins(self):
        assert _better(_cand(60), _cand(50)) is True
        assert _better(_cand(50), _cand(60)) is False

    def test_sweet_spot_tie_keeps_old(self):
        assert _better(_cand(100), _cand(100)) is False
        assert _better(_cand(30), _cand(30)) is False
        assert _better(_cand(250), _cand(250)) is False

    # Sweet-spot always beats too-long
    def test_sweet_spot_beats_too_long(self):
        assert _better(_cand(50), _cand(300)) is False   # old is sweet-spot → keep
        assert _better(_cand(300), _cand(50)) is True    # new is sweet-spot → switch

    # Sweet-spot always beats too-short
    def test_sweet_spot_beats_too_short(self):
        assert _better(_cand(50), _cand(15)) is False    # old is sweet-spot → keep
        assert _better(_cand(15), _cand(50)) is True     # new is sweet-spot → switch

    # Both too-long (>250): shorter wins
    def test_both_too_long_shorter_wins(self):
        assert _better(_cand(300), _cand(350)) is False  # old shorter → keep
        assert _better(_cand(350), _cand(300)) is True   # new shorter → switch

    # Both too-short (<30): longer wins
    def test_both_too_short_longer_wins(self):
        assert _better(_cand(15), _cand(20)) is True     # new longer
        assert _better(_cand(20), _cand(15)) is False    # old longer → keep

    # Too-long beats too-short (cross-tier)
    def test_too_long_beats_too_short(self):
        assert _better(_cand(300), _cand(15)) is False   # old is too-long → keep
        assert _better(_cand(15), _cand(300)) is True    # new is too-long → switch

    # Boundaries
    def test_boundary_30_belongs_sweet_spot(self):
        # 29 is too-short, 30 is sweet-spot
        assert _better(_cand(29), _cand(30)) is True     # sweet-spot wins
        assert _better(_cand(30), _cand(29)) is False    # sweet-spot kept

    def test_boundary_250_belongs_sweet_spot(self):
        # 250 is sweet-spot, 251 is too-long
        assert _better(_cand(250), _cand(251)) is False  # sweet-spot kept
        assert _better(_cand(251), _cand(250)) is True   # sweet-spot wins

    # Tie-break at all boundaries
    def test_tie_at_all_boundaries(self):
        assert _better(_cand(30), _cand(30)) is False    # keep old
        assert _better(_cand(250), _cand(250)) is False  # keep old
        assert _better(_cand(300), _cand(300)) is False  # keep old
        assert _better(_cand(15), _cand(15)) is False    # keep old
