"""Test lib/lemmatize.py — inflectional and derivational lemmatization.

Covers historical error cases from commits 0b69bb9, 48c805c, 870edb4, b6a9a83.

NOTE: lemmatize() first checks COCA membership — words already in COCA
return as-is. Words NOT in COCA go through IRREG dict → regular patterns.
"""

import pytest
from lemmatize import lemmatize, lemmatize_conservative


@pytest.mark.parametrize("word,expected", [
    # ── Cross-POS false positive: same-length mappings rejected ──
    ("abode", "abode"),         # n.住所 ≠ abide v.忍受 (both 5 chars)
    ("abide", "abide"),         # base form stays
    # ── Double-consonant patterns — NOT in COCA → reduces ──
    ("crammed", "cram"),        # -ed doubled consonant
    ("forsaken", "forsake"),    # -en past participle
    ("stopped", "stop"),        # standard doubled -ed
    # ── -y ↔ -i patterns — NOT in COCA → reduces ──
    ("cried", "cry"),           # -ied → -y
    ("babies", "baby"),         # -ies → -y
    # ── Regular inflection NOT in COCA → reduces ──
    ("walked", "walk"),
    ("cats", "cat"),
    ("bumps", "bump"),
    # ── Irregular verbs from IRREG dict ──
    ("was", "be"),
    ("were", "be"),
    ("had", "have"),
    ("done", "do"),
    ("went", "go"),             # IRREG: went→go
    ("worse", "bad"),           # IRREG: worse→bad
    ("worst", "bad"),           # IRREG: worst→bad
    # ── Comparatives NOT in COCA → reduces ──
    ("happier", "happy"),       # -ier → -y
    ("happiest", "happy"),      # -iest → -y
    ("smallest", "small"),
    ("biggest", "big"),
    # ── Words in COCA → stay as-is ──
    ("beer", "beer"),           # noun, not bee+r
    ("anger", "anger"),         # noun, not ange+r
    ("fiber", "fiber"),         # noun, not fibe+r
    ("running", "running"),     # in COCA as noun/adj
    ("sitting", "sitting"),     # in COCA
    ("making", "making"),       # in COCA
    ("walking", "walking"),     # in COCA
    ("loved", "loved"),         # in COCA
    ("closest", "closest"),     # in COCA
    ("fastest", "fastest"),     # in COCA
    ("sacred", "sacred"),       # in COCA
    ("tremendous", "tremendous"), # in COCA
    ("best", "best"),           # in COCA
    ("better", "better"),       # in COCA
    # ── Plural forms ──
    ("knives", "knife"),        # -ves → -f (NOT in COCA)
    ("kisses", "kiss"),         # -es → stem
    # ── Unchanged irregular ──
    ("cut", "cut"),
    ("put", "put"),
    ("read", "read"),
    ("shed", "shed"),
])
def test_lemmatize(word, expected, coca_set):
    """Test lemmatize() against historical error cases."""
    result = lemmatize(word, coca_set)
    assert result == expected, \
        f"lemmatize({word!r}) = {result!r}, expected {expected!r}"


@pytest.mark.xfail(reason="Known limitation: equal-length irregulars (ran→run)")
@pytest.mark.parametrize("word,expected", [
    ("ran", "run"),
    ("sat", "sit"),
])
def test_lemmatize_equal_length_irreg_known_limitation(word, expected, coca_set):
    result = lemmatize(word, coca_set)
    assert result == expected


def test_lemmatize_conservative_no_cross_pos():
    assert lemmatize_conservative("abode") == "abode"
    assert lemmatize_conservative("abide") == "abide"


def test_lemmatize_conservative_valid_inflections():
    assert lemmatize_conservative("straying") == "stray"
    assert lemmatize_conservative("eruptions") == "eruption"
    assert lemmatize_conservative("caterpillars") == "caterpillar"


def test_derivational_adjective_distinguished(coca_set):
    """distinguished(adj) stays — spaCy detects adjective."""
    result = lemmatize("distinguished", coca_set, "a distinguished fisherman")
    assert result == "distinguished", f"got {result!r}"


def test_derivational_adjective_accomplished(coca_set):
    """accomplished(adj) stays."""
    result = lemmatize("accomplished", coca_set, "an accomplished pianist")
    assert result == "accomplished", f"got {result!r}"


def test_regular_verb_still_reduces(coca_set):
    """Regular verbs with verbal context reduce."""
    result = lemmatize("pondered", coca_set, "He pondered the question.")
    assert result == "ponder", f"got {result!r}"


def test_blundering_spacy_env_note(coca_set):
    """blundering with adj context: behavior depends on spaCy model availability.

    In production (with en_core_web_sm installed), spaCy detects adjective →
    blundering stays. Without spaCy, lemminflect fallback is used.
    This test only verifies the function doesn't crash.
    """
    result = lemmatize("blundering", coca_set, "I felt awkward and blundering.")
    # Either outcome is valid depending on spaCy availability
    assert result in ("blundering", "blunder"), \
        f"Unexpected result: {result!r}"


@pytest.mark.parametrize("word,expected", [
    ("smallest", "small"),      # regular -est
    ("biggest", "big"),         # doubled consonant -est
])
def test_superlative_reduction(word, expected, coca_set):
    """Superlatives NOT in COCA reduce (near-zero false positive rate)."""
    result = lemmatize(word, coca_set)
    assert result == expected
