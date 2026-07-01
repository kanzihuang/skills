"""Test lib/lemmatize.py — VERB + NOUN channels + irregular comparative lookup.

ADJ channel removed — English -er/-est ambiguity makes it unreliable
(121 false positives: baker→bak, beer→bee, etc.).

Irregular comparatives/superlatives handled by explicit closed-set lookup
(better→good, worse→bad, more→much — 12 entries).

Regular comparatives (closest, fastest, happier) are NOT reduced — known
trade-off, minor impact on vocabulary grouping.
"""

import pytest
from lemmatize import lemmatize, lemmatize_conservative


@pytest.mark.parametrize("word,expected", [
    # ── lemminflect VERB channel ──
    ("running", "run"),
    ("sitting", "sit"),
    ("making", "make"),
    ("walking", "walk"),
    ("loved", "love"),
    ("walked", "walk"),
    ("stopped", "stop"),
    ("crammed", "cram"),
    ("pondered", "ponder"),
    # ── lemminflect VERB: irregular ──
    ("went", "go"),
    ("ran", "run"),
    ("sat", "sit"),
    ("had", "have"),
    ("was", "be"),
    ("were", "be"),
    ("done", "do"),
    ("cried", "cry"),
    ("bound", "bind"),
    ("stung", "sting"),
    ("dove", "dive"),
    ("flung", "fling"),
    ("ground", "grind"),
    ("forsaken", "forsake"),
    ("given", "give"),
    ("written", "write"),
    # ── lemminflect NOUN channel ──
    ("men", "man"),
    ("feet", "foot"),
    ("babies", "baby"),
    ("knives", "knife"),
    ("kisses", "kiss"),
    ("bumps", "bump"),
    ("cats", "cat"),
    # ── Irregular comparatives/superlatives (explicit lookup) ──
    ("better", "good"),
    ("best", "good"),
    ("worse", "bad"),
    ("worst", "bad"),
    ("more", "much"),
    ("most", "much"),
    ("least", "little"),
    ("further", "far"),
    ("elder", "old"),
    # ── Words in COCA — stay ──
    ("beer", "beer"),
    ("anger", "anger"),
    ("fiber", "fiber"),
    ("tremendous", "tremendous"),
    ("sacred", "sacred"),
    ("cut", "cut"),
    ("put", "put"),
    ("read", "read"),
    ("bad", "bad"),
    ("good", "good"),
    ("much", "much"),
    ("less", "little"),         # irregular comparative dict
    # ── Known trade-offs: ADJ channel removed ──
    ("distinguished", "distinguish"),  # needs sentence context
    ("accomplished", "accomplish"),
    ("closest", "closest"),           # regular comparative, not reduced
    ("fastest", "fastest"),
    ("happier", "happier"),          # known trade-off
    ("happiest", "happy"),          # -iest handled by lemminflect VERB
    ("smallest", "smallest"),
    ("biggest", "biggest"),
    # ── Cross-POS: abode → abide (correct as past tense) ──
    ("abode", "abide"),
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


def test_contraction_without_apostrophe(coca_set):
    assert lemmatize("dont", coca_set) == "do"
    assert lemmatize("isnt", coca_set) == "be"


def test_beer_is_noun_not_bee(coca_set):
    """beer is a noun, no ADJ channel → no false reduction."""
    assert lemmatize("beer", coca_set) == "beer"


def test_spacy_path(coca_set):
    """With sentence context, spaCy handles derivational adjectives."""
    try:
        import spacy
        spacy.load("en_core_web_sm")
    except Exception:
        pytest.skip("spaCy model not installed")
    assert lemmatize("distinguished", coca_set,
                     "He was a distinguished fisherman.") == "distinguished"
    assert lemmatize("accomplished", coca_set,
                     "She is an accomplished pianist.") == "accomplished"
    # spaCy also handles regular comparatives correctly
    assert lemmatize("closest", coca_set,
                     "the closest star") == "close"
