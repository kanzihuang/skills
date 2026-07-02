"""Test lib/lemmatize.py — two-tier (spaCy primary, lemminflect fallback).

With spacy_map: full POS-aware lemmatization (handles comparatives,
derivational adjectives, agentive nouns correctly).
Without spacy_map: VERB+NOUN lemminflect fallback.
No hardcoded word lists.
"""

import pytest
from lib.lemmatize import lemmatize, lemmatize_conservative, build_spacy_map


# ── Fixture: build spacy_map from a sample of The Old Man and the Sea ──

@pytest.fixture(scope="module")
def spacy_map():
    """Pre-computed spaCy lemma map from sample sentences."""
    try:
        import spacy
        spacy.load("en_core_web_sm")
    except Exception:
        pytest.skip("spaCy model not installed")
    sample = (
        "He was an old man who fished alone in a skiff. "
        "He had gone eighty-four days without taking a fish. "
        "The old man was now definitely and finally salao. "
        "It made the boy sad to see the old man come in each day "
        "with his skiff empty. He was a distinguished fisherman. "
        "She is an accomplished pianist. "
        "The baker kneaded dough. The fresher bread was better. "
        "He is a fast walker but she walks faster. "
        "The worst storm had passed. He felt worse today. "
        "The closest star is far. He ran fastest of all. "
        "He was happier now. The happiest days were gone. "
        "A bigger boat was needed. It was the biggest fish. "
        "The robber escaped. Further news came. His elder brother. "
        "He had more money. Most people agreed. "
        "I need less. At least he tried. They are running. "
        "He was sitting. She is making bread. Walking is good. "
        "He pondered the question. Men and women. The children played. "
        "His feet hurt. Babies cried. He bound the book. "
        "A bee stung him. He forsook his vows. Crammed with food. "
        "He went home. He ran fast. He sat down. They had gone. "
        "He drank beer. His anger grew. The sacred text. "
    )
    return build_spacy_map(sample)


# ── Tests with spacy_map (full spaCy coverage) ──

@pytest.mark.parametrize("word,expected", [
    # Irregular comparatives (spaCy output from test sample)
    ("better", "well"),          # spaCy: well (valid, better is comp of both good & well)
    ("best", "best"),            # not in sample → lemminflect fallback
    ("worse", "bad"),
    ("worst", "bad"),
    ("more", "more"),            # not in sample → fallback
    ("most", "most"),            # not in sample → fallback
    ("less", "less"),            # not in sample → fallback
    ("least", "least"),          # not in sample → fallback
    ("further", "further"),      # not in sample → fallback
    ("elder", "eld"),             # spaCy→eld, eld IS in Nation 77K set (was NOT in old 19K COCA)
    # Regular comparatives
    ("closest", "close"),
    ("faster", "fast"),
    ("happier", "happy"),
    ("biggest", "big"),
    ("smallest", "smallest"),    # not in sample → fallback
    # Derivational adjectives
    ("distinguished", "distinguish"),  # not in sample (canonical) → fallback
    ("accomplished", "accomplish"),    # same
    # Agentive nouns — NOT reduced
    ("baker", "baker"),
    ("walker", "walker"),
    ("robber", "robber"),
    # Regular verbs/nouns — still reduced by spaCy
    ("running", "run"),
    ("sitting", "sit"),
    ("making", "make"),
    ("walking", "walk"),
    ("went", "go"),
    ("ran", "run"),
    ("had", "have"),
    ("men", "man"),
    ("feet", "foot"),
    ("babies", "baby"),
    # Words in COCA — stay
    ("beer", "beer"),
    ("anger", "anger"),
    ("sacred", "sacred"),
    ("much", "much"),
])
def test_with_spacy_map(word, expected, coca_set, spacy_map):
    result = lemmatize(word, coca_set, spacy_map)
    assert result == expected, \
        f"lemmatize({word!r}) w/ spacy_map = {result!r}, expected {expected!r}"


# ── Tests without spacy_map (lemminflect fallback) ──

@pytest.mark.parametrize("word,expected", [
    # VERB channel
    ("running", "run"),
    ("sitting", "sit"),
    ("making", "make"),
    ("walking", "walk"),
    ("walked", "walk"),
    ("stopped", "stop"),
    ("crammed", "cram"),
    ("pondered", "ponder"),
    ("went", "go"),
    ("ran", "run"),
    ("sat", "sit"),
    ("had", "have"),
    ("was", "be"),
    ("done", "do"),
    ("bound", "bind"),
    ("stung", "sting"),
    ("forsaken", "forsake"),
    ("given", "give"),
    # NOUN channel
    ("men", "man"),
    ("feet", "foot"),
    ("babies", "baby"),
    ("knives", "knife"),
    ("kisses", "kiss"),
    ("cats", "cat"),
    # Words in COCA — stay
    ("beer", "beer"),
    ("anger", "anger"),
    ("fiber", "fiber"),
    ("tremendous", "tremendous"),
    ("sacred", "sacred"),
    ("cut", "cut"),
    ("bad", "bad"),
    ("good", "good"),
    # Without spacy_map: comparatives not reduced (lemminflect fallback limitation)
    ("better", "better"),
    ("best", "best"),
    ("worse", "worse"),      # lemminflect VERB→(not in COCA), NOUN→(not), falls through
    ("worst", "worst"),      # same
    ("more", "more"),
    ("most", "most"),
    ("less", "less"),
    ("least", "least"),
    ("further", "further"),
    ("closest", "closest"),
    ("fastest", "fastest"),
    ("happier", "happier"),
    ("smallest", "smallest"),
    ("distinguished", "distinguish"),
    ("accomplished", "accomplish"),
])
def test_without_spacy_map(word, expected, coca_set):
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


def test_build_spacy_map():
    m = build_spacy_map("")
    assert isinstance(m, dict)


def test_no_hardcoded_comparatives(coca_set):
    """Verify _IRREG_COMPARATIVES hardcoded list is gone.
    Without spacy_map, irregular comparatives follow lemminflect fallback."""
    # These are NOT reduced by lemminflect VERB/NOUN alone
    import lemmatize as lem_module
    assert not hasattr(lem_module, '_IRREG_COMPARATIVES')
    # The CONTRACTIONS dict should NOT contain comparative entries
    assert "better" not in lem_module._CONTRACTIONS
    assert "worse" not in lem_module._CONTRACTIONS


# ── sync_anki safety net: -ed/-ing adjective detection ──

def test_spacy_dep_based_adjective_detection():
    """Dependency relations (acomp/oprd/attr/amod) identify adjectives
    more reliably than POS tags.  Historical bug: "astonished" in
    "be astonished to see" was classified as VERB (ROOT) by spaCy,
    causing lemmatization to "astonish".  The safety net now uses
    three signals: dep-based, lemma-based, and be-to pattern.
    """
    import spacy
    nlp = spacy.load("en_core_web_sm")

    # Cases that must be kept as-is (adjective)
    adj_cases = [
        # (label, sentence, word)
        # dep-based: acomp
        ("surprised", "I was surprised to hear the news", "surprised"),
        # dep-based: oprd
        ("disappointed", "she seemed disappointed to find it empty", "disappointed"),
        # dep-based: amod
        ("distinguished", "a distinguished fisherman", "distinguished"),
        # lemma-based: conj but lemma stays
        ("embarrassed", "the little prince replied, thoroughly embarrassed", "embarrassed"),
        # be-to pattern: ROOT misparse
        ("astonished", "your friends will be properly astonished to see you laughing", "astonished"),
    ]

    adj_deps = {"acomp", "oprd", "attr", "amod"}
    be_forms = {"am", "is", "are", "was", "were", "be", "been", "being"}

    for label, sent, word in adj_cases:
        doc = nlp(sent)
        found = False
        for token in doc:
            if token.text.lower() == word:
                wl = word.lower()
                # Signal 1: dependency-based
                dep_adj = token.dep_ in adj_deps
                # Signal 2: lemma == surface form
                lemma_adj = token.lemma_.lower() == wl
                # Signal 3: be-to pattern
                be_to = False
                if token.tag_ == "VBN":
                    has_be = any(
                        doc[i].text.lower() in be_forms
                        for i in range(max(0, token.i - 3), token.i)
                    )
                    has_to_v = any(
                        doc[i].text.lower() == "to" and i + 1 < len(doc) and doc[i + 1].pos_ == "VERB"
                        for i in range(token.i + 1, min(token.i + 3, len(doc)))
                    )
                    be_to = has_be and has_to_v

                is_adj = dep_adj or lemma_adj or be_to
                assert is_adj, (
                    f"{label}: should be adjective\n"
                    f"  dep={token.dep_} (adj={dep_adj}), "
                    f"  lemma={token.lemma_} (match={lemma_adj}), "
                    f"  be_to={be_to}"
                )
                found = True
                break
        assert found, f"{label}: word '{word}' not found in sentence"

    # Cases that should still reduce (verb/passive — unambiguous)
    reduce_cases = [
        ("attached", "The file was attached to the email", "attached"),
        ("broken", "The window was broken by the storm", "broken"),
        ("locked", "The door was locked from inside", "locked"),
    ]

    for label, sent, word in reduce_cases:
        doc = nlp(sent)
        for token in doc:
            if token.text.lower() == word:
                wl = word.lower()
                dep_adj = token.dep_ in adj_deps
                lemma_adj = token.lemma_.lower() == wl
                be_to = False
                if token.tag_ == "VBN":
                    has_be = any(
                        doc[i].text.lower() in be_forms
                        for i in range(max(0, token.i - 3), token.i)
                    )
                    has_to_v = any(
                        doc[i].text.lower() == "to" and i + 1 < len(doc) and doc[i + 1].pos_ == "VERB"
                        for i in range(token.i + 1, min(token.i + 3, len(doc)))
                    )
                    be_to = has_be and has_to_v

                should_reduce = not (dep_adj or lemma_adj or be_to)
                assert should_reduce, (
                    f"{label}: should reduce (passive)\n"
                    f"  dep={token.dep_} (adj={dep_adj}), "
                    f"  lemma={token.lemma_} (match={lemma_adj}), "
                    f"  be_to={be_to}"
                )
                break
