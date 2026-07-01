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
    """Lemmatize *word* using lemminflect with COCA validation.

    Queries lemminflect across VERB, NOUN, ADJ channels.  Collects all
    candidates that are in COCA and differ from the input, then picks
    the shortest (inflectional reduction).

    Known trade-offs (documented, not patched):
    - ``beer`` → ``bee`` — ADJ channel false positive.  Both are in COCA;
      "bee" is shorter.  Affects <3 vocabulary cards in practice.
    - ``distinguished`` → ``distinguish`` — derivational adjective reduced
      to verb root.  Disambiguation requires sentence context (spaCy).
    - ``less`` → ``less`` — lemminflect treats "less" as its own lemma
      rather than mapping it to "little".
    """
    w = word.lower()

    # 1. Contractions (text-cleaning artifacts)
    if w in _CONTRACTIONS:
        return _CONTRACTIONS[w]

    # 2. lemminflect across VERB → NOUN → ADJ
    try:
        from lemminflect import getLemma
    except ImportError:
        return w

    candidates: set[str] = set()
    for upos in ("VERB", "NOUN", "ADJ"):
        lemmas = getLemma(w, upos)
        if not lemmas:
            continue
        for lemma in lemmas:
            cand = lemma.lower()
            if cand != w and cand in coca_set:
                candidates.add(cand)

    if candidates:
        # Prefer shortest; tiebreak alphabetically for determinism
        return min(candidates, key=lambda x: (len(x), x))

    # 3. No lemmatisation found
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
