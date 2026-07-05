"""Test IPA generation — cmudict lookup and ARPAbet→IPA mapping.

Covers historical errors:
  - ARPAbet→IPA mapping correctness
  - Heteronym disambiguation (read/read, wound/wound)
  - Multi-pronunciation word handling
"""

import pytest
from lib.ipa import _load_cmudict, _cmu_ipa


# ── cmudict loading ──

def test_load_cmudict_returns_dict():
    cmu = _load_cmudict()
    assert isinstance(cmu, dict)
    assert len(cmu) > 100000, f"Expected >100K entries, got {len(cmu)}"


def test_load_cmudict_common_words(cmudict):
    """Common words should be in cmudict with pronunciations."""
    assert "feed" in cmudict or "FEED" in cmudict
    assert "the" in cmudict or "THE" in cmudict


def test_load_cmudict_cached():
    a = _load_cmudict()
    b = _load_cmudict()
    assert a is b


# ── IPA lookup ──

@pytest.mark.parametrize("word,expected_ipa", [
    # ── Single-pronunciation words ──
    ("feed", "/fiːd/"),
    ("shark", "/ʃɑːrk/"),
    ("fish", "/fɪʃ/"),
    ("skiff", "/skɪf/"),
    # ── Multi-pronunciation — returns one of the valid options ──
    ("read", None),       # /riːd/ or /rɛd/ — check it returns something
    ("wound", None),      # /wuːnd/ or /waʊnd/
])
def test_cmu_ipa(word, expected_ipa):
    """cmudict IPA lookup produces expected results."""
    result = _cmu_ipa(word)
    if expected_ipa is not None:
        assert result == expected_ipa, \
            f"_cmu_ipa({word!r}) = {result!r}, expected {expected_ipa!r}"
    else:
        # Multi-pronunciation: just verify it returns something valid
        assert result is not None, f"{word} should have cmudict entry"
        assert result.startswith("/"), f"IPA should start with /: {result}"
        assert result.endswith("/"), f"IPA should end with /: {result}"


def test_cmu_ipa_heteronym_with_claude_hint():
    """Claude's IPA hint helps disambiguate heteronyms.

    read + "/riːd/" → present tense; read + "/rɛd/" → past tense.
    """
    # With hint for present tense
    result = _cmu_ipa("read", "/riːd/")
    assert result == "/riːd/", \
        f"Claude hint /riːd/ should select present tense: got {result}"

    # With hint for past tense
    result = _cmu_ipa("read", "/rɛd/")
    assert result in ("/rɛd/", "/red/"), \
        f"Claude hint /rɛd/ should select past tense: got {result}"


def test_cmu_ipa_wound_disambiguation():
    """wound: noun (injury) → /wuːnd/, verb (past of wind) → /waʊnd/."""
    result_noun = _cmu_ipa("wound", "/wuːnd/")
    assert result_noun == "/wuːnd/"

    result_verb = _cmu_ipa("wound", "/waʊnd/")
    assert result_verb == "/waʊnd/"
