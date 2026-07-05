"""Test match_sentences.py — PySBD segmentation + candidate extraction.

Covers:
  - PySBD sentence splitting accuracy
  - Candidate extraction (order, count limit)
  - Hard 500-char truncation
  - <b> tag insertion
  - select_best_sentence three-tier selection
"""

import pytest
from lib.scripts.match_sentences import (
    split_sentences,
    find_all_sentences,
    hard_truncate,
    select_best_sentence,
    _clean_quote_artifact,
)


# ── PySBD sentence splitting ──


def test_standard_sentence_split():
    """Standard sentences with abbreviation should not be over-split."""
    sents = split_sentences(
        "Hello! This is a test. Dr. Smith arrived."
    )
    assert len(sents) == 3
    assert "Dr. Smith arrived." in sents


def test_dialogue_quote_split():
    """Dialogue with quotes inside should be split correctly."""
    sents = split_sentences(
        '"Draw me a sheep!" he said. "What?"'
    )
    assert len(sents) == 2
    assert '"Draw me a sheep!" he said.' in sents


def test_abbreviation_not_split():
    """Common abbreviations (Mr., Dr., U.S.) should not trigger splits."""
    sents = split_sentences(
        "Mr. Jones and Dr. Lee went to U.S. offices."
    )
    assert len(sents) == 1


# ── Hard truncation ──


def test_hard_truncate_short_sentence_unchanged():
    """Sentences under the cutoff are returned as-is."""
    text, was_truncated = hard_truncate("Short sentence.", max_len=500)
    assert text == "Short sentence."
    assert was_truncated is False


def test_hard_truncate_long_sentence_cut_at_word_boundary():
    """Long sentences (>500 chars) are cut at the last word boundary."""
    long_text = "word " * 300  # ~1500 chars
    text, was_truncated = hard_truncate(long_text, max_len=500)
    assert was_truncated is True
    assert len(text) <= 500
    assert not text.endswith(" ")


# ── Candidate extraction ──


def test_candidates_in_original_order():
    """Candidates are returned in original text order, not by length."""
    text = (
        "The little prince was abashed. "
        "He felt very abashed indeed. "
        "Completely abashed, he looked away."
    )
    results = find_all_sentences(text, ["abashed"], "abash")
    assert len(results) == 3
    assert "little prince" in results[0]["text"]
    assert "very" in results[1]["text"]
    assert "Completely" in results[2]["text"]


def test_candidates_capped_at_five():
    """At most 5 candidates are returned."""
    text = ". ".join([f"Sentence {i} with the word test." for i in range(10)])
    results = find_all_sentences(text, ["test"], "test")
    assert len(results) <= 5


def test_word_not_in_text_returns_empty():
    """Empty list when word is not in text."""
    results = find_all_sentences("No match here.", ["abashed"], "abash")
    assert results == []


def test_b_tag_inserted():
    """<b> tags wrap the matched surface form."""
    text = "The little prince was abashed."
    results = find_all_sentences(text, ["abashed"], "abash")
    assert len(results) == 1
    assert "<b>abashed</b>" in results[0]["text"]


def test_case_insensitive_match_preserves_original():
    """Matching is case-insensitive; <b> preserves original case."""
    text = "ABASHED, he looked away."
    results = find_all_sentences(text, ["abashed"], "abash")
    assert len(results) == 1
    assert "<b>ABASHED</b>" in results[0]["text"]


def test_duplicate_sentences_deduplicated():
    """Identical sentences are deduplicated."""
    text = "He was abashed. He was abashed."
    results = find_all_sentences(text, ["abashed"], "abash")
    assert len(results) == 1


# ── _clean_quote_artifact ──

def test_quote_artifact_no_leading_whitespace():
    """'\" \"X' → '\"X' (no leading whitespace)."""
    assert _clean_quote_artifact('" "No,') == '"No,'


def test_quote_artifact_with_leading_whitespace():
    """'  \" \"X' stripped first, then cleaned → '\"X'."""
    # This is what split_sentences does: strip() then _clean_quote_artifact()
    assert _clean_quote_artifact('  " "No,'.strip()) == '"No,'


def test_quote_artifact_clean_sentence_unchanged():
    """Normal dialogue is untouched."""
    assert _clean_quote_artifact('"Hello," he said.') == '"Hello," he said.'


# ── select_best_sentence three-tier selection ──
#
# Rule:
#   Tier 1: 30 ≤ len ≤ 250 → pick shortest  (sweet spot)
#   Tier 2: only > 250      → pick shortest  (truncatable, but beats <30)
#   Tier 3: all < 30        → pick longest   (best effort)


class TestSelectBestSentence:
    # ── empty ──

    def test_empty_candidates_returns_none(self):
        """[] → None"""
        assert select_best_sentence([]) is None

    # ── single candidate ──

    def test_single_short_candidate(self):
        """[15] (all < 30) → Tier 3, picks 15 (the only one)"""
        candidates = [{"text": "x" * 15, "len": 15, "truncated": False}]
        result = select_best_sentence(candidates)
        assert result["len"] == 15

    def test_single_sweet_spot_candidate(self):
        """[60] (in sweet spot) → Tier 1, picks 60"""
        candidates = [{"text": "x" * 60, "len": 60, "truncated": False}]
        result = select_best_sentence(candidates)
        assert result["len"] == 60

    def test_single_long_candidate(self):
        """[300] (only > 250) → Tier 2, picks 300 (Step 2B will truncate)"""
        candidates = [{"text": "x" * 300, "len": 300, "truncated": False}]
        result = select_best_sentence(candidates)
        assert result["len"] == 300

    # ── boundaries ──

    def test_boundary_exactly_at_min(self):
        """[30, 80] → Tier 1, picks 30 (shortest in sweet spot)"""
        candidates = [
            {"text": "x" * 30, "len": 30, "truncated": False},
            {"text": "x" * 80, "len": 80, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 30

    def test_boundary_exactly_at_max(self):
        """[250, 80] → Tier 1, picks 80 (shortest in sweet spot)"""
        candidates = [
            {"text": "x" * 250, "len": 250, "truncated": False},
            {"text": "x" * 80, "len": 80, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 80

    def test_boundary_just_below_min(self):
        """[29, 25] (all < 30) → Tier 3, picks 29 (longest of the short)"""
        candidates = [
            {"text": "x" * 29, "len": 29, "truncated": False},
            {"text": "x" * 25, "len": 25, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 29

    def test_boundary_just_above_max(self):
        """[251, 280] (only > 250) → Tier 2, picks 251 (shortest to truncate)"""
        candidates = [
            {"text": "x" * 251, "len": 251, "truncated": False},
            {"text": "x" * 280, "len": 280, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 251

    # ── Tier 1: sweet spot (30-250), pick shortest ──

    def test_tier1_picks_shortest_in_sweet_spot(self):
        """[80, 35, 90] → Tier 1, picks 35 (shortest ≥30)"""
        candidates = [
            {"text": "x" * 80, "len": 80, "truncated": False},
            {"text": "x" * 35, "len": 35, "truncated": False},
            {"text": "x" * 90, "len": 90, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 35

    def test_tier1_ignores_too_short(self):
        """[18, 50] → Tier 1, picks 50 (18 < 30, skipped)"""
        candidates = [
            {"text": "x" * 18, "len": 18, "truncated": False},
            {"text": "x" * 50, "len": 50, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 50

    def test_tier1_beats_long(self):
        """[300, 80] → Tier 1, picks 80 (sweet-spot beats > 250)"""
        candidates = [
            {"text": "x" * 300, "len": 300, "truncated": False},
            {"text": "x" * 80, "len": 80, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 80

    def test_tier1_beats_both_short_and_long(self):
        """[14, 35, 300] → Tier 1, picks 35 (sweet-spot beats both < 30 and > 250)"""
        candidates = [
            {"text": "x" * 14, "len": 14, "truncated": False},
            {"text": "x" * 35, "len": 35, "truncated": False},
            {"text": "x" * 300, "len": 300, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 35

    # ── Tier 2: only > 250, pick shortest (truncatable beats < 30) ──

    def test_tier2_long_preferred_over_very_short(self):
        """[14, 18, 300] → Tier 2, picks 300 (truncatable beats useless < 30)"""
        candidates = [
            {"text": "x" * 14, "len": 14, "truncated": False},
            {"text": "x" * 18, "len": 18, "truncated": False},
            {"text": "x" * 300, "len": 300, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 300

    def test_tier2_only_long_picks_shortest(self):
        """[300, 280, 400] → Tier 2, picks 280 (shortest to truncate)"""
        candidates = [
            {"text": "x" * 300, "len": 300, "truncated": False},
            {"text": "x" * 280, "len": 280, "truncated": False},
            {"text": "x" * 400, "len": 400, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 280

    # ── Tier 3: all < 30, pick longest (best effort) ──

    def test_tier3_all_very_short_picks_longest(self):
        """[12, 25, 18] → Tier 3, picks 25 (longest of the useless)"""
        candidates = [
            {"text": "x" * 12, "len": 12, "truncated": False},
            {"text": "x" * 25, "len": 25, "truncated": False},
            {"text": "x" * 18, "len": 18, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 25
