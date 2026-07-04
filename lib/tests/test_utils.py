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
from lib.utils import lemmatize_word, safe_filename


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
        # ── Comparatives & superlatives (ADJ channel + spaCy POS gate) ──
        ("higher", "high"),             # -er comparative
        ("faster", "fast"),             # -er comparative
        ("bigger", "big"),              # -er with doubled consonant
        ("lighter", "light"),           # -er comparative
        ("highest", "high"),            # -est superlative
        ("fastest", "fast"),            # -est superlative
        ("better", "good"),             # irregular comparative
        ("worse", "bad"),              # irregular comparative
        # ── Agentive nouns (-er suffix, NOT comparatives) — spaCy gate ──
        ("baker", "baker"),             # PROPN/NOUN, not reduced
        ("walker", "walker"),           # NOUN, not reduced
        ("robber", "robber"),           # PROPN/NOUN, not reduced
        # ── Base-form nouns ending in -er — spaCy gate ──
        ("beer", "beer"),               # NOUN, not reduced
        ("anger", "anger"),             # NOUN, not reduced
        ("fiber", "fiber"),             # NOUN, not reduced
        # ── Cross-POS same-length — NOT reduced ──
        ("abode", "abode"),             # len(abide) == len(abode), guard rejects
        # ── Words ending in non-ly suffixes that lemminflect ADV would
        #     falsely reduce.  ADV channel is now gated to -ly only. ──
        ("absurd", "absurd"),           # was "absur" — lemminflect ADV treats 'd' as suffix
        ("reflective", "reflective"),   # was "reflect" — lemminflect ADV treats 'ive' as suffix
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
    """Downstream COCA gating for lemmatize_word's edge cases.

    lib.lemmatize.lemmatize('sacred', coca) → 'sacred' (in COCA, VERB→sacre rejected)
    lib.lemmatize.lemmatize('tremendous', coca) → 'tremendous' (in COCA)
    """
    import sys; sys.path.insert(0, '../lib')
    from lib.coca import load_coca
    from lib.lemmatize import lemmatize as lib_lemmatize
    coca = load_coca()
    assert lib_lemmatize("sacred", coca) == "sacred"
    assert lib_lemmatize("tremendous", coca) == "tremendous"


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
