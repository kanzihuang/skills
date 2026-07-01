"""Inflectional lemmatization engine (屈折还原，拒绝跨词性转换).

Delegates all lemmatization to lemminflect — a professional, maintained
library covering the full English irregular/regular inflection space.
COCA membership is the sole validation gate.

Public API
----------
lemmatize(word, coca_set) -> str
    Lemmatize via lemminflect across VERB/NOUN/ADJ; pick shortest
    candidate that is in COCA and differs from the input.

lemmatize_conservative(word) -> str
    Conservative VERB/NOUN-only lemmatization via lemminflect.
"""

from __future__ import annotations


# ============================================================================
# Contractions without apostrophes (text-cleaning artifacts)
# ============================================================================
# lemminflect handles "don't"→"do" but after punctuation cleaning we get
# "dont" — this tiny lookup bridges that gap.

_SPACY = None


def _get_spacy():
    """Load spaCy (cached)."""
    global _SPACY
    if _SPACY is None:
        try:
            import spacy
            _SPACY = spacy.load("en_core_web_sm")
        except Exception:
            pass
    return _SPACY


_CONTRACTIONS: dict[str, str] = {
    "cant": "can", "cannot": "can",
    "wont": "will",
    "dont": "do", "didnt": "do", "doesnt": "do",
    "isnt": "be", "arent": "be", "wasnt": "be", "werent": "be",
    "hasnt": "have", "havent": "have", "hadnt": "have",
    "couldnt": "can", "wouldnt": "will", "shouldnt": "shall",
    "mustnt": "must",
}


# ============================================================================
# Public API
# ============================================================================

def lemmatize(word: str, coca_set: set[str], sentence: str = "") -> str:
    """Lemmatize *word* with COCA validation.

    If *sentence* is provided, uses spaCy's POS-aware lemmatizer
    (handles derivational adjectives like distinguished→distinguished).
    Otherwise falls back to lemminflect across VERB/NOUN/ADJ.

    The only known false positive without sentence context is
    ``distinguished→distinguish`` (derivational adj reduced to verb).
    """
    w = word.lower()

    # 1. Explicit overrides (contractions, beer)
    if w in _CONTRACTIONS:
        return _CONTRACTIONS[w]

    # 2. spaCy — POS-aware (used when sentence context is available)
    if sentence:
        nlp = _get_spacy()
        if nlp is not None:
            try:
                doc = nlp(sentence)
                for token in doc:
                    if token.text.lower() == w:
                        cand = token.lemma_.lower()
                        if cand != w and cand in coca_set:
                            return cand
                        break
            except Exception:
                pass  # fall through to lemminflect

    # 3. lemminflect across VERB → NOUN
    #    ADJ channel is NOT used — English -er/-est morphology is
    #    ambiguous (agentive noun vs comparative vs part-of-root).
    #    ADJ causes 121 false positives (baker→bak, beer→bee) vs
    #    ~12 correct irregular comparative reductions.
    #    Irregular comparatives are handled explicitly below.
    try:
        from lemminflect import getLemma
    except ImportError:
        return w

    candidates: set[str] = set()
    for upos in ("VERB", "NOUN"):
        lemmas = getLemma(w, upos)
        if not lemmas:
            continue
        for lemma in lemmas:
            cand = lemma.lower()
            if cand != w and cand in coca_set:
                candidates.add(cand)

    # 4. Irregular comparatives/superlatives — closed set, explicit
    #    These are not handled by VERB/NOUN channels.
    _IRREG_COMPARATIVES: dict[str, str] = {
        "better": "good", "best": "good",
        "worse": "bad", "worst": "bad",
        "more": "much", "most": "much",
        "less": "little", "least": "little",
        "further": "far", "furthest": "far",
        "farther": "far", "farthest": "far",
        "elder": "old", "eldest": "old",
    }
    if w in _IRREG_COMPARATIVES:
        cand = _IRREG_COMPARATIVES[w]
        if cand in coca_set:
            candidates.add(cand)

    if candidates:
        return min(candidates, key=lambda x: (len(x), x))

    return w


def lemmatize_conservative(word: str) -> str:
    """Conservative VERB/NOUN-only lemmatization via lemminflect.

    Only accepts a lemma that is *strictly shorter* than the input word.
    This avoids cross-POS false positives (abode n. -> abide v.) and is
    suitable for flashcard generation where precision matters more than recall.
    """
    try:
        from lemminflect import getLemma
    except ImportError:
        return word.lower()

    w = word.lower()
    candidates: list[str] = []

    for upos in ("VERB", "NOUN"):
        lemmas = getLemma(w, upos)
        if not lemmas:
            continue
        for lemma in lemmas:
            if lemma != w and len(lemma) < len(w):
                candidates.append(lemma)

    if candidates:
        return min(candidates, key=lambda x: (len(x), x))
    return w
