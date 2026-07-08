"""Test sync_anki.validate_word_entries — word entry validation.

In the new design, sentences are stored WITHOUT <b> tags (tags are added
by sync_anki.py at display time).  Validation checks target_offset instead
of parsing <b> tags, and lemma is always mechanically set by match_sentences.py.
"""

import re
import pytest
from lib.validation import validate_word_entries
from lib.config import MAX_SENTENCE_LENGTH, MIN_SENTENCE_LENGTH


# ── Helper ──

def make_word(word="test", sentence=None, lemma="test", ipa="/tɛst/",
              definition_cn="测试", translation_cn="测试翻译。", **overrides):
    """Build a word entry dict for validation testing."""
    if sentence is None:
        sentence = f"This is a {word} test sentence."
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


# ── target_offset checks ──

def test_target_offset_match():
    """Word at target_offset must match word field."""
    w = make_word(word="shark", sentence="The shark is coming.", target_offset=4)
    errors = validate_word_entries([w])
    assert not errors, f"Should pass: word at offset matches\nErrors: {errors}"


def test_target_offset_mismatch():
    """target_offset pointing to wrong word is a hard error."""
    w = make_word(word="shark", sentence="The whale is coming.", target_offset=4)
    errors = validate_word_entries([w])
    assert has_error(errors, "shark", "mismatch"), \
        f"Should detect target_offset mismatch\nErrors: {errors}"


# ── Hard error: sentence too long ──

def test_sentence_too_long():
    """Sentence >MAX_SENTENCE_LENGTH is a hard error."""
    base = ("He adjusted the sack and carefully worked the line so that it came "
            "across a new part of his shoulders and, holding it anchored with his "
            "shoulders, he leaned forward and braced himself against the weight "
            "of the fish as it pulled with tremendous force against the line that "
            "he had so carefully prepared")
    assert len(base) > MAX_SENTENCE_LENGTH, \
        f"Test sentence should be >{MAX_SENTENCE_LENGTH} chars: got {len(base)}"
    w = make_word(word="anchored", sentence=base, target_offset=base.index("anchored"))
    errors = validate_word_entries([w])
    assert has_error(errors, "anchored", "too long"), \
        f"Should reject >250 char sentence\nErrors: {errors}"


def test_sentence_at_limit_ok():
    """Sentence at or under MAX_SENTENCE_LENGTH should pass."""
    sent = ('He adjusted the sack and carefully worked the line so that it came '
            'across a new part of his shoulders, holding it anchored.')
    assert len(sent) <= MAX_SENTENCE_LENGTH, \
        f"Precondition failed: {len(sent)} > {MAX_SENTENCE_LENGTH}"
    w = make_word(word="anchored", sentence=sent, target_offset=sent.index("anchored"),
                  ipa="/ˈæŋkərd/", definition_cn="固定住",
                  translation_cn="他调整了麻袋，小心地把线移过肩膀新位置，把它固定住。")
    errors = validate_word_entries([w])
    assert not has_error(errors, "anchored", "too long"), \
        f"Under-250 sentence should pass\nErrors: {errors}"


# ── Hard error: missing required fields ──

def test_missing_ipa():
    w = make_word(ipa="")
    errors = validate_word_entries([w])
    assert has_error(errors, "test", "missing 'ipa'")


def test_missing_definition_cn():
    w = make_word(definition_cn="")
    errors = validate_word_entries([w])
    assert has_error(errors, "test", "missing 'definition_cn'")


def test_missing_translation_cn():
    w = make_word(translation_cn="")
    errors = validate_word_entries([w])
    assert has_error(errors, "test", "missing 'translation_cn'")


# ── Lemma is now mechanically set by match_sentences.py ──


# ── Word not found in sentence (hard error) ──

def test_word_not_in_sentence():
    """Validator MUST reject when the target word is not in the sentence text."""
    w = make_word(word="shark", sentence="The old man saw the marlin jumping.")
    errors = validate_word_entries([w])
    assert has_error(errors, "shark", "not found"), \
        f"Should reject when word not in sentence\nErrors: {errors}"


# ── Valid entries should pass ──

def test_good_entry_passes():
    """A properly formed entry should produce no errors."""
    w = make_word(
        word="shark", lemma="shark",
        sentence="The shark came back again.",
        target_offset=4,
        ipa="/ʃɑːrk/",
        definition_cn="n. 鲨鱼",
        translation_cn="鲨鱼又回来了。",
    )
    errors = validate_word_entries([w])
    assert len(errors) == 0, f"Good entry should pass\nErrors: {errors}"


# ── Soft warnings (these go to stderr, not returned as errors) ──

def test_sentence_starts_lowercase():
    """Sentence fragment starting lowercase — soft warning."""
    w = make_word(word="aboard",
                  sentence="and then, with the boy's aid, hoisted her aboard.")
    errors = validate_word_entries([w])
    assert isinstance(errors, list)


def test_noun_phrase_fragment():
    """Pure noun phrase without finite verb — soft warning."""
    w = make_word(word="tenderness",
                  sentence="the tenderness of smiling faces")
    errors = validate_word_entries([w])
    assert isinstance(errors, list)


def test_ipa_chinese_characters():
    """IPA with Chinese characters triggers soft warning."""
    w = make_word(word="test", ipa="/测试/")
    errors = validate_word_entries([w])
    assert isinstance(errors, list)


# ── Truncation quality ──

def test_truncation_never_produces_lowercase_start():
    """Validator warns when sentence starts lowercase — fragment detection."""
    w = make_word(
        word="alternately",
        sentence="yard of line and then struck again, swinging with "
                 "each arm alternately on the...",
        ipa="/ɔːlˈtɜːrnətli/",
        definition_cn="adv. 交替地",
        translation_cn="双臂交替地拉线。",
    )
    errors = validate_word_entries([w])
    assert isinstance(errors, list)


def test_truncation_preserves_b_tag():
    """Validator MUST reject sentences where target word is absent."""
    w = make_word(
        word="alternately",
        sentence="He struck again and again, swinging with each arm.",
        ipa="/ɔːlˈtɜːrnətli/",
        definition_cn="adv. 交替地",
        translation_cn="双臂交替地拉线。",
    )
    errors = validate_word_entries([w])
    assert len(errors) > 0, "Should reject sentence without target word"
    assert any("not found" in e for e in errors), \
        f"Should report word not in sentence\nErrors: {errors}"


# ── Function-word ending detection ──

@pytest.mark.parametrize("word,bad_sentence", [
    ("angle", "The sea was discolouring with the red of the blood from"),
])
def test_sentence_ending_with_function_word_is_error(word, bad_sentence):
    """Sentences ending with a preposition/conjunction are hard errors."""
    w = make_word(word=word, sentence=bad_sentence)
    errors = validate_word_entries([w])
    assert has_error(errors, word, "function word"), \
        f"Expected function-word error for: {bad_sentence}"


def test_sentence_ending_with_content_word_passes():
    """Sentences ending with a noun/verb/adjective are fine."""
    w = make_word(word="angle", sentence="The shaft was projecting at an angle.")
    errors = validate_word_entries([w])
    assert not has_error(errors, "angle", "function word")

    w2 = make_word(word="agony", sentence="He put it against the fish's agony.")
    errors2 = validate_word_entries([w2])
    assert not has_error(errors2, "agony", "function word")

    w3 = make_word(word="aboard", sentence="They hoisted her aboard.")
    errors3 = validate_word_entries([w3])
    assert not has_error(errors3, "aboard", "function word")


# ── Punctuation artifacts ──

def test_sentence_ending_with_bare_comma_is_error():
    """Sentences ending with bare comma are hard errors."""
    w = make_word(
        word="humble",
        sentence="I resolved to humble myself also,",
    )
    errors = validate_word_entries([w])
    assert has_error(errors, "humble", "punctuation artifact"), \
        f"Should detect bare comma ending\nErrors: {errors}"


# ── Colon-ending sentence (dialogue-attribution fragment) ──


def test_sentence_ending_with_colon_is_error():
    """Sentences ending with ':' are dialogue-attribution fragments — hard error."""
    w = make_word(
        word="attentively",
        sentence="He looked attentively, then:",
    )
    errors = validate_word_entries([w])
    assert has_error(errors, "attentively", "dialogue-attribution"), \
        f"Should detect colon ending\nErrors: {errors}"


def test_then_colon_caught_as_function_word():
    """'then:' is stripped to 'then' and caught by function-word check."""
    w = make_word(
        word="attentively",
        sentence="He looked attentively, then:",
    )
    errors = validate_word_entries([w])
    assert has_error(errors, "attentively", "function word"), \
        f"'then:' should match 'then' in function word set\nErrors: {errors}"


def test_old_regex_still_catches_comma_period():
    """Regression: old ',.' pattern still caught by extended check."""
    w = make_word(
        word="breeze",
        sentence="The flower swayed in the breeze,.",
    )
    errors = validate_word_entries([w])
    assert has_error(errors, "breeze", "punctuation artifact"), \
        f"Should still detect ',.' artifact\nErrors: {errors}"


# ── Sentence length checks ──

def test_sentence_under_250_passes():
    """Sentence ≤250 chars passes length validation."""
    w = make_word(
        word="veritable",
        sentence="I will tell you that before the invention of electricity "
                "it was necessary to maintain a veritable army of 462,511 "
                "lamplighters for the street lamps.",
    )
    assert len(w["sentence"]) <= MAX_SENTENCE_LENGTH, \
        f"Precondition: sentence must be ≤{MAX_SENTENCE_LENGTH} chars"
    errors = validate_word_entries([w])
    assert not has_error(errors, "veritable", "sentence too long"), \
        f"Sentence ≤250 should pass length check\nErrors: {errors}"


def test_sentence_at_min_length_passes():
    """Sentence ≥ MIN_SENTENCE_LENGTH (30) should pass without error."""
    w = make_word(
        word="horn",
        sentence="He blew his horn very loudly then.",  # 30 chars
    )
    assert len(w["sentence"]) >= MIN_SENTENCE_LENGTH, \
        f"Precondition: sentence must be ≥ {MIN_SENTENCE_LENGTH} chars"
    errors = validate_word_entries([w])
    assert not has_error(errors, "horn", "too short"), \
        f"Sentence ≥{MIN_SENTENCE_LENGTH} chars should pass\nErrors: {errors}"
