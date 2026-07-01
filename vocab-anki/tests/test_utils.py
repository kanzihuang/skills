"""Test utils.py — lemmatize_word, safe_filename.

NOTE: utils.lemmatize_word() uses lemminflect VERB/NOUN channels only,
with a len(lemma) < len(word) guard. It does NOT have COCA gating.
COCA gating happens later in the pipeline via lib.lemmatize.lemmatize()
and sync_anki.resolve_lemma().

Historical errors covered:
  - Cross-POS prevention: abode→abode (same length, rejected)
  - Regular inflection reduction: straying→stray, eruptions→eruption
  - Known bug: sacred→sacre, tremendous→tremendou (no COCA guard here,
    caught downstream by resolve_lemma's COCA gating)
"""

import pytest
from utils import lemmatize_word, safe_filename


@pytest.mark.parametrize(
    "word,expected",
    [
        # ── Known issues (no COCA guard in lemmatize_word): ──
        ("sacred", "sacre"),            # lemminflect sees -ed, reduces
        ("tremendous", "tremendou"),    # lemminflect sees -ous reduction
        # ── COCA gating not needed for these (lemminflect handles correctly): ──
        ("beer", "beer"),               # unchanged — not a recognized inflection
        ("anger", "anger"),             # unchanged
        ("fiber", "fiber"),             # unchanged
        # ── Regular reductions via lemminflect ──
        ("straying", "stray"),          # -ing
        ("eruptions", "eruption"),      # -s
        ("caterpillars", "caterpillar"), # -s
        ("pondered", "ponder"),         # -ed
        ("attached", "attach"),         # -ed
        ("burning", "burn"),            # -ing
        # ── Cross-POS same-length — NOT reduced ──
        ("abode", "abode"),             # len(abide) == len(abode), guard rejects
        # ── Words already base form ──
        ("fish", "fish"),
        ("water", "water"),
    ],
)
def test_lemmatize_word(word, expected):
    """Test utils.lemmatize_word() — note no COCA gating at this layer."""
    result = lemmatize_word(word)
    assert result == expected, f"lemmatize_word({word!r}) = {result!r}, expected {expected!r}"


def test_lemmatize_word_strictly_shorter():
    """lemmatize_word requires strictly shorter lemma (guards cross-POS)."""
    result = lemmatize_word("abode")
    assert result == "abode"  # 5 chars → stays 5 chars, not abide


def test_pipeline_gating_note():
    """Downstream COCA gating catches lemmatize_word's mistakes.

    lemmatize_word('sacred') → 'sacre' (incorrect)
    But sync_anki.resolve_lemma('sacred', '') uses COCA gating → stays 'sacred'
    And lib.lemmatize.lemmatize('sacred', coca_set) → 'sacred' (in COCA)
    """
    # This test documents the pipeline behavior, not a bug
    from sync_anki import resolve_lemma
    assert resolve_lemma("sacred", "") == "sacred"
    assert resolve_lemma("tremendous", "") == "tremendous"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("word", "word"),
        ("word/special:chars", "word_special_chars"),
        ("hello world", "hello_world"),
        ("test'case", "test_case"),
        ("what?", "what"),
        ("   spaces   ", "spaces"),
        ("mix of *symbols*!", "mix_of__symbols"),
    ],
)
def test_safe_filename(filename, expected):
    """safe_filename sanitizes to alphanumeric + underscore."""
    result = safe_filename(filename)
    assert result == expected, f"safe_filename({filename!r}) = {result!r}"
