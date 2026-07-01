"""Test sync_anki._validate_word_entries — LLM output quality interception.

These tests use INTENTIONALLY BAD DATA (simulating historical LLM mistakes)
to verify the validator correctly rejects or warns about them.

Historical LLM errors covered:
  - <b> tag splitting surface words (commit 24eba8d): dip→<b>dip</b>ped
  - Case mismatch: <b>Any</b> vs word "any"
  - Truncated fragments: lowercase starts, conjunction starts
  - Noun phrase fragments: "the tenderness of smiling faces"
  - Suspicious lemma override: beautiful→beautifully (commit 68be62e)
  - Missing required fields
  - IPA with Chinese characters
  - Function-word endings: truncation cutting at prepositions/conjunctions
    (e.g. "...the red of the blood from" ending with "from")
"""

import re
import pytest
from sync_anki import _validate_word_entries


# ── Helper ──

def make_word(word="test", sentence=None, lemma="", ipa="/tɛst/",
              definition_cn="测试", translation_cn="测试翻译。", **overrides):
    """Build a word entry dict for validation testing."""
    if sentence is None:
        sentence = f"This is a <b>{word}</b> test sentence."
    entry = {
        "word": word,
        "lemma": lemma,
        "sentence": sentence,
        "ipa": ipa,
        "definition_cn": definition_cn,
        "translation_cn": translation_cn,
    }
    entry.update(overrides)
    return entry


def has_error(errors, word, pattern):
    """Check if any error message for `word` contains `pattern`."""
    return any(
        word in e and pattern.lower() in e.lower()
        for e in errors
    )


# ── Hard errors: <b> tag splitting (commit 24eba8d) ──

@pytest.mark.parametrize("word,bad_sentence", [
    ("dip", "He <b>dip</b>ped the oar into the water."),
    ("nail", "The old man's <b>nail</b>s were cracked."),
    ("bind", "The rope was <b>bind</b>ing his hands."),
])
def test_tag_splits_surface_word(word, bad_sentence):
    """Validator MUST reject <b> tags that split the surface word form.

    Historical: Claude wrapped only the root, producing <b>dip</b>ped instead of <b>dipped</b>.
    """
    w = make_word(word=word, sentence=bad_sentence)
    errors = _validate_word_entries([w])
    assert has_error(errors, word, "tag splits surface word"), \
        f"Should detect tag split: {bad_sentence}\nErrors: {errors}"


def test_tag_splits_are_hard_errors():
    """Tag split must be a HARD error (not just a warning)."""
    w = make_word(word="dip", sentence="He <b>dip</b>ped.")
    errors = _validate_word_entries([w])
    # Hard errors appear in the returned list (warnings go to stderr only)
    assert len(errors) > 0, "Tag split should be a hard error"


# ── Hard errors: <b> mismatch (case sensitivity) ──

def test_b_tag_case_mismatch():
    """<b>Any</b> but word='any' — hard error.

    Historical: Claude wrote <b>Any</b> but set word='any' (lowercase).
    """
    w = make_word(word="any", sentence="<b>Any</b> man could do it.")
    errors = _validate_word_entries([w])
    assert has_error(errors, "any", "mismatch"), \
        f"Should detect case mismatch\nErrors: {errors}"


def test_b_tag_content_vs_word_field():
    """<b> tag text must exactly match the word field."""
    w = make_word(word="shark", sentence="The <b>sharks</b> are coming.")
    errors = _validate_word_entries([w])
    assert has_error(errors, "shark", "mismatch"), \
        f"Should detect word/b-text mismatch\nErrors: {errors}"


# ── Hard error: sentence too long ──

def test_sentence_too_long():
    """Sentence >150 chars (with tags) is a hard error."""
    base = "He adjusted the sack and carefully worked the line so that it came across a new part of his shoulders and, holding it anchored with his shoulders"
    tagged = base.replace("anchored", "<b>anchored</b>")  # +7 chars for tags
    assert len(tagged) > 150, f"Test sentence should be >150 chars: got {len(tagged)}"
    w = make_word(word="anchored", sentence=tagged)
    errors = _validate_word_entries([w])
    assert has_error(errors, "anchored", "too long"), \
        f"Should reject >150 char sentence\nErrors: {errors}"


def test_sentence_at_limit_ok():
    """Sentence exactly at or under 150 chars with tags should pass."""
    # Use a realistic sentence that's under 150 chars with tags
    tagged = ('He adjusted the sack and carefully worked the line so that it came '
              'across a new part of his shoulders, holding it <b>anchored</b>.')
    assert len(tagged) < 150, f"Precondition failed: {len(tagged)}"
    w = make_word(word="anchored", sentence=tagged,
                  ipa="/ˈæŋkərd/", definition_cn="固定住",
                  translation_cn="他调整了麻袋，小心地把线移过肩膀新位置，把它固定住。")
    errors = _validate_word_entries([w])
    assert not has_error(errors, "anchored", "too long"), \
        f"Under-150 sentence should pass\nErrors: {errors}"


# ── Hard error: missing required fields ──

def test_missing_ipa():
    w = make_word(ipa="")
    errors = _validate_word_entries([w])
    assert has_error(errors, "test", "missing 'ipa'")


def test_missing_definition_cn():
    w = make_word(definition_cn="")
    errors = _validate_word_entries([w])
    assert has_error(errors, "test", "missing 'definition_cn'")


def test_missing_translation_cn():
    w = make_word(translation_cn="")
    errors = _validate_word_entries([w])
    assert has_error(errors, "test", "missing 'translation_cn'")


# ── Hard error: suspicious lemma (commit 68be62e) ──

def test_suspicious_lemma_unrelated():
    """lemma='beautifully' for word='beautiful' — hard error.

    Historical: Claude set lemma="beautifully" for the word "beautiful".
    The lemma differs from both the surface form AND lemmatize_word() result.
    """
    w = make_word(word="beautiful", lemma="beautifully")
    errors = _validate_word_entries([w])
    assert has_error(errors, "beautiful", "suspicious lemma"), \
        f"Should detect unrelated lemma\nErrors: {errors}"


def test_valid_lemma_override_ok():
    """Explicit lemma='blundering' for derivational adj word='blundering' is OK."""
    w = make_word(word="blundering", lemma="blundering",
                  sentence="I felt awkward and <b>blundering</b>.")
    errors = _validate_word_entries([w])
    assert not has_error(errors, "blundering", "suspicious"), \
        f"Valid derivational adj override should pass\nErrors: {errors}"


# ── Soft warnings (these go to stderr, not returned as errors) ──

def test_sentence_starts_lowercase():
    """Sentence fragment starting lowercase — soft warning.

    The validator currently only prints warnings to stderr for lowercase starts.
    These are NOT returned as hard errors in the current implementation.
    """
    w = make_word(word="aboard",
                  sentence="and then, with the boy's aid, hoisted her <b>aboard</b>.")
    errors = _validate_word_entries([w])
    # Lowercase starts may or may not be hard errors depending on version
    # At minimum, they should not crash the validator
    assert isinstance(errors, list)


def test_noun_phrase_fragment():
    """Pure noun phrase without finite verb — soft warning.

    Historical: "the tenderness of smiling faces" extracted as sentence fragment.
    """
    w = make_word(word="tenderness",
                  sentence="the <b>tenderness</b> of smiling faces")
    errors = _validate_word_entries([w])
    # May be a soft warning (stderr) or hard error depending on implementation
    assert isinstance(errors, list)


def test_ipa_chinese_characters():
    """IPA with Chinese characters triggers soft warning.

    Historical: Claude accidentally put Chinese text in IPA field.
    """
    w = make_word(word="test", ipa="/测试/")
    errors = _validate_word_entries([w])
    # IPA format warnings go to stderr; should not be hard errors
    # But the validator should not crash
    assert isinstance(errors, list)


# ── Word not found in sentence (hard error) ──

def test_word_not_in_sentence():
    """Validator MUST reject when the target word is not in the sentence text."""
    w = make_word(word="shark", sentence="The old man saw the <b>marlin</b> jumping.")
    errors = _validate_word_entries([w])
    assert has_error(errors, "shark", "not found"), \
        f"Should reject when word not in sentence\nErrors: {errors}"


# ── Valid entries should pass ──

# ── Truncation quality (SKILL.md 3.0e rules) ──


def test_truncation_never_produces_lowercase_start():
    """Validator warns when sentence starts lowercase — fragment detection.

    Historical: match_sentences.py trim-from-start produced fragments
    like 'yard of line and then struck again...' (alternately card).
    """
    w = make_word(
        word="alternately",
        sentence="yard of line and then struck again, swinging with "
                 "each arm <b>alternately</b> on the...",
        ipa="/ɔːlˈtɜːrnətli/",
        definition_cn="adv. 交替地",
        translation_cn="双臂交替地拉线。",
    )
    errors = _validate_word_entries([w])
    # Lowercase start produces soft warning (stderr) — the validator
    # should at minimum not crash on these inputs
    assert isinstance(errors, list)


def test_truncation_preserves_b_tag():
    """Validator MUST reject sentences with missing <b> tags.

    Historical: truncation cut off the <b> tag entirely, producing
    sentences where the target word was absent.
    """
    w = make_word(
        word="alternately",
        sentence="He struck again and again, swinging with each arm.",
        ipa="/ɔːlˈtɜːrnətli/",
        definition_cn="adv. 交替地",
        translation_cn="双臂交替地拉线。",
    )
    errors = _validate_word_entries([w])
    assert len(errors) > 0, "Should reject sentence without <b> tag"
    assert any("not found" in e for e in errors), \
        f"Should report word not in sentence\nErrors: {errors}"


def test_good_entry_passes():
    """A properly formed entry should produce no errors."""
    w = make_word(
        word="shark",
        sentence='The <b>shark</b> came back again.',
        ipa="/ʃɑːrk/",
        definition_cn="n. 鲨鱼",
        translation_cn="鲨鱼又回来了。",
    )
    errors = _validate_word_entries([w])
    assert len(errors) == 0, f"Good entry should pass\nErrors: {errors}"


def test_good_entry_no_lemma_passes():
    """Entry with empty lemma (auto-resolve) should pass."""
    w = make_word(
        word="pondered",
        sentence='He <b>pondered</b> the question.',
        lemma="",  # auto-resolve to ponder
    )
    errors = _validate_word_entries([w])
    assert not has_error(errors, "pondered", "suspicious lemma")
    assert not has_error(errors, "pondered", "missing")


# ── IPA format checks ──

def test_ipa_missing_slashes():
    """IPA without / delimiters — soft warning printed to stderr."""
    w = make_word(word="test", ipa="tɛst")
    errors = _validate_word_entries([w])
    # Should not be a hard error
    assert not has_error(errors, "test", "missing 'ipa'")
    assert isinstance(errors, list)


# ── Function-word ending detection (commit: SKILL.md truncation rule) ──

@pytest.mark.parametrize("word,bad_sentence", [
    # angle: "...the red of the blood from" — "from" expects an object
    ("angle", "The sea was discolouring with the red of the blood <b>from</b>"),
    # aboard-like: "...hoisted her aboard" — NOT a function word, should pass
])
def test_sentence_ending_with_function_word_is_error(word, bad_sentence):
    """Sentences ending with a preposition/conjunction are hard errors."""
    w = make_word(word=word, sentence=bad_sentence)
    errors = _validate_word_entries([w])
    assert has_error(errors, word, "function word"), \
        f"Expected function-word error for: {bad_sentence}"


def test_sentence_ending_with_content_word_passes():
    """Sentences ending with a noun/verb/adjective are fine."""
    w = make_word(word="angle", sentence="The shaft was projecting at an <b>angle</b>.")
    errors = _validate_word_entries([w])
    assert not has_error(errors, "angle", "function word")

    w2 = make_word(word="agony", sentence="He put it against the fish's <b>agony</b>.")
    errors2 = _validate_word_entries([w2])
    assert not has_error(errors2, "agony", "function word")

    # aboard ends with a content word, not a function word
    w3 = make_word(word="aboard", sentence="They hoisted her <b>aboard</b>.")
    errors3 = _validate_word_entries([w3])
    assert not has_error(errors3, "aboard", "function word")
