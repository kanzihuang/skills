"""Test sync_anki.resolve_lemma — multi-strategy lemma resolution.

Covers historical errors:
  - beer→beer (COCA guard, commit b6a9a83)
  - fastest→fast (-est always runs, commit 870edb4)
  - closest→close (drop-e + COCA validated)
  - Explicit lemma override trusted unconditionally
"""

import pytest
from sync_anki import resolve_lemma


@pytest.mark.parametrize("word,json_lemma,expected", [
    # ── COCA guard: word already in COCA → no reduction ──
    ("beer", "", "beer"),
    ("anger", "", "anger"),
    ("fiber", "", "fiber"),
    ("fastest", "", "fast"),      # -est always reduces
    ("slowest", "", "slow"),
    ("biggest", "", "big"),
    ("happiest", "", "happy"),
    ("closest", "", "close"),     # drop-e + COCA validated
    # ── -er reduction ──
    ("smaller", "", "small"),
    ("bigger", "", "big"),
    ("happier", "", "happy"),
    # ── Regular inflections ──
    ("walked", "", "walk"),
    ("walking", "", "walk"),
    ("cats", "", "cat"),
    # ── Explicit lemma override — unconditionally trusted ──
    ("blundering", "blundering", "blundering"),
    ("distinguished", "distinguished", "distinguished"),
    # ── Base forms ──
    ("shark", "", "shark"),
    ("fish", "", "fish"),
    # ── IRREG fallback ──
    ("went", "", "go"),
    ("was", "", "be"),
    ("had", "", "have"),
    # ── Contractions ──
    ("don't", "", "don't"),       # no hint → stays
    ("don't", "do", "do"),        # explicit lemma → trusted
])
def test_resolve_lemma(word, json_lemma, expected):
    result = resolve_lemma(word, json_lemma)
    assert result == expected, \
        f"resolve_lemma({word!r}, {json_lemma!r}) = {result!r}, expected {expected!r}"


def test_explicit_lemma_trusted():
    result = resolve_lemma("blundering", "blundering")
    assert result == "blundering"


def test_empty_json_lemma_triggers_auto_resolve():
    result = resolve_lemma("walking", "")
    assert result == "walk"
