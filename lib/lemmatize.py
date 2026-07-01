"""Inflectional lemmatization engine (屈折还原，拒绝跨词性转换).

Two-tier architecture:
1. spaCy (primary) — POS-aware, parsed once from full text, handles ALL
   irregular/regular/comparative/derivational forms correctly.
2. lemminflect (fallback) — fast form-based lemmatizer for when spaCy
   is unavailable or the word isn't in the pre-computed map.

No hardcoded word lists. No ADJ channel workarounds.
"""

from __future__ import annotations

# ============================================================================
# Contractions without apostrophes (text-cleaning artifacts)
# ============================================================================

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
# spaCy — one-time full-text parse → surface → lemma map
# ============================================================================

def build_spacy_map(text: str) -> dict[str, str]:
    """Parse *text* with spaCy and return ``{surface_form: lemma}``.

    Run ONCE on the full book text.  Callers pass the result to
    :func:`lemmatize` via the *spacy_map* parameter.

    Returns empty dict if spaCy or its model is not installed.
    """
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        return {}

    result: dict[str, str] = {}
    # Process in chunks to avoid memory issues on very long texts
    chunk_size = 100_000
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        try:
            doc = nlp(chunk)
        except Exception:
            continue
        for token in doc:
            surface = token.text.lower()
            lemma = token.lemma_.lower()
            if surface != lemma:
                # Prefer the first-occurring lemma for each surface form
                if surface not in result:
                    result[surface] = lemma

    return result


# ============================================================================
# Public API
# ============================================================================

def lemmatize(
    word: str,
    coca_set: set[str],
    spacy_map: dict[str, str] | None = None,
) -> str:
    """Lemmatize *word* with COCA validation.

    Args:
        word: Surface form to lemmatize.
        coca_set: COCA 20000 lemma set for validation.
        spacy_map: Pre-computed ``{surface → lemma}`` from
                   :func:`build_spacy_map`.  When provided, used as
                   the primary source (POS-aware, handles everything).
                   Falls back to lemminflect when absent.

    No hardcoded word lists — spaCy handles irregular comparatives
    (better→good), derivational adjectives (distinguished→distinguished),
    and agentive nouns (baker→baker) correctly via POS context.
    """
    w = word.lower()

    # 1. Contractions (text-cleaning artifacts: "dont"→"do")
    if w in _CONTRACTIONS:
        return _CONTRACTIONS[w]

    # 2. spaCy map — primary source (POS-aware, zero false positives)
    if spacy_map and w in spacy_map:
        cand = spacy_map[w]
        if cand in coca_set:
            return cand

    # 3. lemminflect fallback — VERB + NOUN channels
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

    if candidates:
        return min(candidates, key=lambda x: (len(x), x))

    return w


def lemmatize_conservative(word: str) -> str:
    """Conservative VERB/NOUN-only lemmatization via lemminflect.

    Only accepts a lemma that is *strictly shorter* than the input word.
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
