"""Test match_sentences.py — PySBD segmentation + candidate extraction.

In the new design, sentences are stored WITHOUT <b> tags. Each result
has 'target_offset', 'matched_form', and 'text' fields.
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


# ── Candidate extraction ──


def test_candidates_in_original_order():
    text = (
        "The little prince was abashed. "
        "He felt very abashed indeed. "
        "Completely abashed, he looked away."
    )
    results = find_all_sentences(text, ["abashed"])
    assert len(results) == 3
    assert "little prince" in results[0]["text"]
    assert "very" in results[1]["text"]
    assert "Completely" in results[2]["text"]


def test_candidates_not_capped():
    """All candidates are returned (no MAX_CANDIDATES cap)."""
    text = ". ".join([f"Sentence {i} with the word test." for i in range(10)])
    results = find_all_sentences(text, ["test"])
    assert len(results) == 10


def test_word_not_in_text_returns_empty():
    results = find_all_sentences("No match here.", ["abashed"])
    assert results == []


def test_target_offset_and_matched_form():
    """target_offset marks the word position, matched_form is the surface form."""
    text = "The little prince was abashed."
    results = find_all_sentences(text, ["abashed"])
    assert len(results) == 1
    assert "abashed" in results[0]["text"]
    assert results[0]["target_offset"] >= 0
    assert results[0]["matched_form"] == "abashed"


def test_case_insensitive_match_preserves_original():
    """Matching is case-insensitive; matched_form preserves original case."""
    text = "ABASHED, he looked away."
    results = find_all_sentences(text, ["abashed"])
    assert len(results) == 1
    assert results[0]["matched_form"] == "ABASHED"


def test_duplicate_sentences_deduplicated():
    text = "He was abashed. He was abashed."
    results = find_all_sentences(text, ["abashed"])
    assert len(results) == 1


# ── _clean_quote_artifact ──

def test_quote_artifact_no_leading_whitespace():
    assert _clean_quote_artifact('" "No,') == '"No,'


def test_quote_artifact_with_leading_whitespace():
    assert _clean_quote_artifact('  " "No,'.strip()) == '"No,'


def test_quote_artifact_clean_sentence_unchanged():
    assert _clean_quote_artifact('"Hello," he said.') == '"Hello," he said.'


# ── select_best_sentence three-tier selection ──


class TestSelectBestSentence:

    def test_empty_candidates_returns_none(self):
        assert select_best_sentence([]) is None

    def test_single_short_candidate(self):
        candidates = [{"text": "x" * 15, "len": 15, "truncated": False}]
        result = select_best_sentence(candidates)
        assert result["len"] == 15

    def test_single_sweet_spot_candidate(self):
        candidates = [{"text": "x" * 60, "len": 60, "truncated": False}]
        result = select_best_sentence(candidates)
        assert result["len"] == 60

    def test_single_long_candidate(self):
        candidates = [{"text": "x" * 300, "len": 300, "truncated": False}]
        result = select_best_sentence(candidates)
        assert result["len"] == 300

    def test_boundary_exactly_at_min(self):
        candidates = [
            {"text": "x" * 30, "len": 30, "truncated": False},
            {"text": "x" * 80, "len": 80, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 30

    def test_boundary_exactly_at_max(self):
        candidates = [
            {"text": "x" * 250, "len": 250, "truncated": False},
            {"text": "x" * 100, "len": 100, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 100

    def test_tier2_all_long_picks_shortest(self):
        candidates = [
            {"text": "x" * 300, "len": 300, "truncated": False},
            {"text": "x" * 400, "len": 400, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 300

    def test_tier3_all_short_picks_longest(self):
        candidates = [
            {"text": "x" * 10, "len": 10, "truncated": False},
            {"text": "x" * 20, "len": 20, "truncated": False},
        ]
        result = select_best_sentence(candidates)
        assert result["len"] == 20
