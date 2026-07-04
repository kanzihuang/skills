"""Test match_sentences.py — PySBD segmentation + candidate extraction.

Covers:
  - PySBD sentence splitting accuracy
  - Candidate extraction (order, count limit)
  - Hard 500-char truncation
  - <b> tag insertion
"""

import pytest
from lib.scripts.match_sentences import (
    split_sentences,
    find_all_sentences,
    hard_truncate,
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
