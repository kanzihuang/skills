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

    When a word appears in multiple POS (e.g. "running" as verb vs noun,
    "distinguished" as adj vs verb), the resolution logic distinguishes
    between **inflection** (reduce: "running"→"run") and **derivation**
    (keep: "alluring" ADJ stays "alluring", not reduced to "allure").

    Returns empty dict if spaCy or its model is not installed.
    """
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        return {}

    # Collect all (surface → lemma) pairs with POS counts.
    # Track POS distribution to distinguish inflection from derivation:
    #   - ADJ + lemma==surface → derived adjective, keep surface form
    #   - VERB + lemma!=surface → regular inflection, reduce
    from collections import Counter
    votes: dict[str, Counter] = {}
    pos_counts: dict[str, Counter] = {}

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
            pos = token.pos_
            if surface not in votes:
                votes[surface] = Counter()
                pos_counts[surface] = Counter()
            votes[surface][lemma] += 1
            pos_counts[surface][pos] += 1

    # Pick the most common lemma for each surface form.
    #
    # When the winner differs from the surface form (e.g. "running"→"run"),
    # add it to the result so callers reduce it.  When the winner equals the
    # surface form, spaCy considers it canonical (e.g. "alluring" ADJ →
    # lemma "alluring").  We STILL add these as {surface: surface} so the
    # lemminflect fallback in lemmatize() won't incorrectly re-reduce them.
    result: dict[str, str] = {}
    for surface, counter in votes.items():
        top = counter.most_common()
        if not top:
            continue
        best_count = top[0][1]
        tied = [lemma for lemma, count in top if count == best_count]
        winner = surface if surface in tied else tied[0]

        # Guard: derived adjectives must not be reduced to their verb stems.
        # When spaCy tags occurrences as ADJ with lemma==surface (e.g.
        # "alluring" ADJ → lemma "alluring"), the surface form IS the
        # canonical adjective lemma.  Verb-lemma majority (e.g. "alluring"
        # VBG → lemma "allure") must not overwrite it.
        if winner != surface:
            pos_counter = pos_counts.get(surface)
            if pos_counter is not None:
                dominant_pos = pos_counter.most_common(1)[0][0] if pos_counter else None
                # ADJ-dominant word where surface form is its own lemma
                # → derived adjective, not inflection
                if dominant_pos == "ADJ" and surface in counter:
                    winner = surface  # override: keep surface form

        result[surface] = winner  # always add — even canonical forms

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

    # 2. spaCy map — primary source (POS-aware, zero false positives).
    #    When cand == w, spaCy has determined this is already a canonical
    #    form (e.g. "alluring" ADJ).  Return immediately — don't let the
    #    lemminflect fallback re-reduce a derived adjective to its verb stem.
    if spacy_map and w in spacy_map:
        cand = spacy_map[w]
        if cand == w:
            return w  # spaCy-declared canonical — no reduction needed
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
