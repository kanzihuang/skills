"""Test utils.py — lemmatize_word, safe_filename.

lemmatize_word() is now a thin wrapper over the unified
lib.lemmatize.lemmatize() which has full COCA gating + Nation CV.
Previously known bugs (sacred→sacre, tremendous→tremendou) are fixed.

Historical errors covered:
  - Regular inflection reduction: straying→stray, eruptions→eruption
  - Nation CV: better/worse kept as own word families
  - COCA gate: sacred, tremendous no longer falsely reduced
"""

import pytest
from lib.utils import lemmatize_word, safe_filename, build_sentence_regex


@pytest.mark.parametrize(
    "word,expected",
    [
        # ── Now fixed: lemmatize_word delegates to unified lemmatize() with COCA + Nation CV ──
        ("sacred", "sacred"),           # was "sacre" — COCA gate + Nation CV
        ("tremendous", "tremendous"),   # was "tremendou" — COCA gate + Nation CV
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
        ("lighter", "lighter"),         # in COCA as noun family, Nation CV keeps
        ("highest", "high"),            # -est superlative
        ("fastest", "fast"),            # -est superlative
        ("better", "better"),           # Nation CV: better is own word family
        ("worse", "worse"),             # Nation CV: worse is own word family
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


def test_build_sentence_regex_importable():
    """build_sentence_regex is importable from lib.utils without side effects."""
    import re
    pattern = build_sentence_regex("hello world.")
    assert re.search(pattern, "hello  world.")
    assert re.search(pattern, "hello\nworld.")
    assert not re.search(pattern, "goodbye")


class TestValidatePlainText:
    """Mechanical HTML detection in source text."""

    def test_plain_text_passes(self):
        """Normal narrative text does not trigger exit."""
        from lib.utils import validate_plain_text
        validate_plain_text("Once upon a time there was a little prince.")

    def test_doctype_html_exits(self):
        """<!DOCTYPE html> triggers SystemExit."""
        from lib.utils import validate_plain_text
        with pytest.raises(SystemExit):
            validate_plain_text("<!DOCTYPE html><html>...")

    def test_html_tag_exits(self):
        """<html> triggers SystemExit."""
        from lib.utils import validate_plain_text
        with pytest.raises(SystemExit):
            validate_plain_text("<html lang=\"en\"><head>...")

    @pytest.mark.parametrize("sig", ["<head>", "<body>", "<meta ", "<title>"])
    def test_other_html_signatures_exit(self, sig):
        """Each HTML signature triggers SystemExit."""
        from lib.utils import validate_plain_text
        with pytest.raises(SystemExit):
            validate_plain_text(sig + " some content")

    def test_html_after_500_chars_not_detected(self):
        """HTML signatures past the first 500 chars are not scanned."""
        from lib.utils import validate_plain_text
        # 500 chars of padding pushes <html> beyond the scan window
        text = "x" * 500 + "<html>"
        validate_plain_text(text)  # should not raise
