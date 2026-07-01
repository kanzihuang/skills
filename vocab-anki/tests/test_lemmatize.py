"""Test lib/lemmatize.py — lemminflect-based lemmatization with COCA validation.

Covers historical error cases.  IRREG dict replaced by lemminflect.
Key behavioral changes from refactoring:
  - Words in COCA: VERB channel checked first; if VERB reduces → accept.
    Otherwise stay (no ADJ/ADV false positives: beer→beer, sacred→sacred).
  - Words NOT in COCA: all POS channels tried (VERB > NOUN > ADJ > ADV).
  - _try_est/_try_er run BEFORE COCA check (closest→close, fastest→fast).
  - Irregular comparatives/superlatives in COCA handled by _SPECIAL dict.
"""

import pytest
from lemmatize import lemmatize, lemmatize_conservative


@pytest.mark.parametrize("word,expected", [
    # ── lemminflect VERB channel (words in COCA → VERB-only check) ──
    ("beer", "beer"),            # in COCA, VERB→same → stays ✅
    ("anger", "anger"),          # in COCA, VERB→same → stays
    ("fiber", "fiber"),          # in COCA, VERB→same → stays
    ("sacred", "sacred"),        # in COCA, VERB→sacre (not in COCA) → stays ✅
    ("tremendous", "tremendous"), # in COCA, VERB→same → stays
    # ── lemminflect VERB channel reduces correctly (in COCA, but VERB reduces) ──
    ("running", "run"),          # in COCA, but VERB→run (in COCA) → reduce ✅
    ("sitting", "sit"),          # in COCA, VERB→sit → reduce
    ("making", "make"),          # in COCA, VERB→make → reduce
    ("walking", "walk"),         # in COCA, VERB→walk → reduce
    ("loved", "love"),           # in COCA, VERB→love → reduce
    # ── Words NOT in COCA — all POS channels ──
    ("went", "go"),              # NOT in COCA, VERB→go ✅
    ("ran", "run"),              # NOT in COCA, VERB→run (was blocked by len guard)
    ("sat", "sit"),              # NOT in COCA, VERB→sit
    ("had", "have"),             # NOT in COCA, VERB→have
    ("was", "be"),
    ("were", "be"),
    ("done", "do"),
    ("cried", "cry"),
    ("babies", "baby"),
    ("happier", "happy"),
    ("happiest", "happy"),
    ("men", "man"),
    ("feet", "foot"),
    ("bound", "bind"),
    ("stung", "sting"),
    ("dove", "dive"),
    ("flung", "fling"),
    ("ground", "grind"),
    # ── _try_est/_try_er before COCA check ──
    ("closest", "close"),         # in COCA, but _try_est→close ✅
    ("fastest", "fast"),          # in COCA, _try_est→fast
    ("smallest", "small"),
    ("biggest", "big"),
    # ── _SPECIAL dict: irregular comparatives in COCA ──
    ("better", "good"),           # in COCA, _SPECIAL→good
    ("best", "good"),
    ("worse", "bad"),
    ("worst", "bad"),
    ("more", "much"),
    ("most", "much"),
    ("less", "little"),
    ("least", "little"),
    ("further", "far"),
    ("elder", "old"),
    # ── Regular inflection NOT in COCA ──
    ("walked", "walk"),
    ("cats", "cat"),
    ("bumps", "bump"),
    ("stopped", "stop"),
    ("crammed", "cram"),
    ("forsaken", "forsake"),
    ("knives", "knife"),
    ("kisses", "kiss"),
    # ── Cross-POS: abode → abide (correct linguistically) ──
    ("abode", "abide"),           # NOT in COCA, VERB→abide (past tense)
    # ── Unchanged irregular ──
    ("cut", "cut"),
    ("put", "put"),
    ("read", "read"),
    ("shed", "shed"),
    ("bad", "bad"),
    ("good", "good"),
    ("much", "much"),
])
def test_lemmatize(word, expected, coca_set):
    result = lemmatize(word, coca_set)
    assert result == expected, \
        f"lemmatize({word!r}) = {result!r}, expected {expected!r}"


def test_lemmatize_conservative_no_cross_pos():
    assert lemmatize_conservative("abode") == "abode"
    assert lemmatize_conservative("abide") == "abide"


def test_lemmatize_conservative_valid_inflections():
    assert lemmatize_conservative("straying") == "stray"
    assert lemmatize_conservative("eruptions") == "eruption"
    assert lemmatize_conservative("caterpillars") == "caterpillar"


def test_derivational_adjective_distinguished(coca_set):
    """distinguished(adj) should stay — depends on spaCy model availability."""
    result = lemmatize("distinguished", coca_set, "a distinguished fisherman")
    # With spaCy: "distinguished". Without: falls through to lemminflect VERB→distinguish
    assert result in ("distinguished", "distinguish")


def test_derivational_adjective_accomplished(coca_set):
    """accomplished(adj) should stay — depends on spaCy model availability."""
    result = lemmatize("accomplished", coca_set, "an accomplished pianist")
    assert result in ("accomplished", "accomplish")


def test_regular_verb_still_reduces(coca_set):
    result = lemmatize("pondered", coca_set, "He pondered the question.")
    assert result == "ponder"


def test_blundering_context_dependent(coca_set):
    """Behavior depends on spaCy availability."""
    result = lemmatize("blundering", coca_set, "I felt awkward and blundering.")
    assert result in ("blundering", "blunder")


def test_contraction_without_apostrophe(coca_set):
    """dont→do, isnt→be etc. handled by _SPECIAL dict."""
    assert lemmatize("dont", coca_set) == "do"
    assert lemmatize("isnt", coca_set) == "be"
    assert lemmatize("didnt", coca_set) == "do"
