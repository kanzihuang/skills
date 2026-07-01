"""Inflectional lemmatization engine (屈折还原，拒绝跨词性转换).

Shared library that reduces English surface forms to their dictionary
base form using only inflectional morphology -- never crossing part-of-speech
boundaries.

Public API
----------
lemmatize(word, coca_set) -> str
    Comprehensive lemmatization (lemminflect + COCA validation + regular patterns).
    Used by vocab-list for full-book vocabulary extraction.

lemmatize_conservative(word) -> str
    Conservative VERB/NOUN-only lemmatization via lemminflect.
    Used by vocab-anki to avoid false positives in flashcard generation.
"""

from __future__ import annotations


# ============================================================================
# Tiny special-case lookup (text-cleaning artifacts + blocked comparatives)
# ============================================================================
# lemminflect handles virtually everything, but two narrow cases need
# explicit overrides:
#
# 1. Contractions without apostrophes (text-cleaning artifacts)
#    "dont"→"do", "isnt"→"be" — lemminflect expects "don't", "isn't".
#
# 2. Irregular comparatives/superlatives that happen to be in COCA
#    (blocked by the VERB-only COCA guard in _try_lemminflect).
#    e.g. better→good, best→good, further→far.
#
# Everything else is delegated to lemminflect — 236-hand-entry IRREG dict
# eliminated.

_SPECIAL: dict[str, str] = {
    # ── Contractions without apostrophes ──
    "cant": "can", "cannot": "can",
    "wont": "will",
    "dont": "do", "didnt": "do", "doesnt": "do",
    "isnt": "be", "arent": "be", "wasnt": "be", "werent": "be",
    "hasnt": "have", "havent": "have", "hadnt": "have",
    "couldnt": "can", "wouldnt": "will", "shouldnt": "shall",
    "mustnt": "must",

    # ── Irregular comparatives/superlatives in COCA ──
    "better": "good", "best": "good",
    "worse": "bad", "worst": "bad",
    "more": "much", "most": "much",
    "less": "little", "least": "little",
    "further": "far", "furthest": "far",
    "farther": "far", "farthest": "far",
    "elder": "old", "eldest": "old",
}


# ============================================================================
# Derivational adjective detection (prevents cross-POS lemmatization)
# ============================================================================

_SPACY = None  # cached spaCy model


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


def _spacy_is_adj(word: str, sentence: str) -> bool:
    """Use spaCy to check if a word is an adjective in sentence context."""
    nlp = _get_spacy()
    if nlp is None:
        return False
    try:
        doc = nlp(sentence)
        for token in doc:
            if token.text.lower() == word.lower():
                return token.pos_ == "ADJ"
    except Exception:
        pass
    return False


def _is_derivational_adj(w: str, sentence: str = "") -> bool:
    """Check whether an -ing/-ed word is more likely a derivational adjective.

    If *sentence* is provided, uses spaCy's POS tagger (context-aware,
    most accurate).  Otherwise falls back to lemminflect for -ing forms
    only (-ed is too unreliable without context).
    """
    if sentence:
        return _spacy_is_adj(w, sentence)
    if not w.endswith("ing"):
        return False
    try:
        from lemminflect import getLemma
    except ImportError:
        return False
    adj = getLemma(w, "ADJ")
    verb = getLemma(w, "VERB")
    adj_unchanged = adj and all(a == w for a in adj)
    verb_changes = verb and any(v != w for v in verb)
    return adj_unchanged and verb_changes


# ============================================================================
# lemminflect-based lemmatization (replaces hand-maintained IRREG dict)
# ============================================================================

def _try_lemminflect(w: str, coca_set: set[str]) -> list[str]:
    """Query lemminflect for lemmas across VERB/NOUN/ADJ/ADV.

    If *w* is already in COCA, only the VERB channel is consulted
    (most reliable for inflectional reduction).  Other POS channels
    can produce false positives for canonical words (beer→bee,
    sacred→sac).

    If *w* is NOT in COCA, all POS channels are tried in priority
    order (VERB > NOUN > ADJ > ADV).

    lemminflect handles ALL irregular forms — 236-hand-entry IRREG
    dict eliminated.
    """
    try:
        from lemminflect import getLemma
    except ImportError:
        return []

    # Only trust VERB channel when word is already canonical.
    if w in coca_set:
        lemmas = getLemma(w, "VERB")
        if lemmas:
            for lemma in lemmas:
                cand = lemma.lower()
                if cand != w and cand in coca_set:
                    return [cand]
        return []

    # Word NOT in COCA — try all POS channels
    for upos in ("VERB", "NOUN", "ADJ", "ADV"):
        lemmas = getLemma(w, upos)
        if not lemmas:
            continue
        for lemma in lemmas:
            cand = lemma.lower()
            if cand == w:
                continue
            if cand in coca_set:
                return [cand]

    return []


# ============================================================================
# Regular inflectional pattern helpers (internal)
# ============================================================================

def _try_ing(w: str, coca_set: set[str], sentence: str = "") -> list[str]:
    """-ing forms: walking->walk, making->make, running->run, sitting->sit."""
    if not w.endswith("ing") or len(w) <= 4:
        return []
    if _is_derivational_adj(w, sentence):
        return []
    base = w[:-3]  # walk, mak, runn, sitt
    results: list[str] = []
    # plain (walking->walk)
    if base in coca_set:
        results.append(base)
    # dropped-e (making->make)
    if (base + "e") in coca_set:
        results.append(base + "e")
    # doubled consonant (running->run, sitting->sit)
    if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
        single = base[:-1]
        if single in coca_set:
            results.append(single)
    return results


def _try_ed(w: str, coca_set: set[str], sentence: str = "") -> list[str]:
    """-ed forms: walked->walk, loved->love, stopped->stop, cried->cry."""
    if not w.endswith("ed") or len(w) <= 3:
        return []
    if _is_derivational_adj(w, sentence):
        return []
    results: list[str] = []
    # -ied -> -y (cried->cry)
    if w.endswith("ied") and len(w) > 4:
        cand = w[:-3] + "y"
        if cand in coca_set:
            results.append(cand)
    base = w[:-2]  # walk, lov, stopp
    if base in coca_set:
        results.append(base)
    if (base + "e") in coca_set:
        results.append(base + "e")
    if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
        single = base[:-1]
        if single in coca_set:
            results.append(single)
    return results


def _try_s_es(w: str, coca_set: set[str]) -> list[str]:
    """Plural nouns / 3sg verbs: cats->cat, kisses->kiss, babies->baby."""
    if not w.endswith("s") or len(w) <= 2:
        return []
    results: list[str] = []
    # -ies -> -y (babies->baby, flies->fly)
    if w.endswith("ies") and len(w) > 4:
        cand = w[:-3] + "y"
        if cand in coca_set:
            results.append(cand)
    # -ses/-shes/-ches/-xes/-zes -> strip -es (kisses->kiss)
    for sfx in ("ses", "shes", "ches", "xes", "zes"):
        if w.endswith(sfx) and len(w) > 4:
            cand = w[:-2]
            if cand in coca_set:
                results.append(cand)
    # plain -s (cats->cat)
    cand = w[:-1]
    if cand in coca_set and len(cand) >= 2:
        results.append(cand)
    # -ves -> -f/-fe (knives->knife, wolves->wolf)
    if w.endswith("ves") and len(w) > 4:
        for sfx in ("f", "fe"):
            cand = w[:-3] + sfx
            if cand in coca_set:
                results.append(cand)
    return results


def _try_er(w: str, coca_set: set[str]) -> list[str]:
    """Comparative -er: bigger->big, smaller->small, happier->happy.

    Requires stem length ≥ 3 to prevent false positives like beer→be.
    """
    if not w.endswith("er") or len(w) <= 3:
        return []
    results: list[str] = []
    if w.endswith("ier") and len(w) > 4:
        cand = w[:-3] + "y"
        if cand in coca_set and len(cand) >= 3:
            results.append(cand)
    base = w[:-2]
    if len(base) >= 3:  # guard: stem must be ≥3 chars (be→beer rejected)
        if base in coca_set:
            results.append(base)
        if (base + "e") in coca_set:
            results.append(base + "e")
        if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
            single = base[:-1]
            if single in coca_set:
                results.append(single)
    return results


def _try_est(w: str, coca_set: set[str]) -> list[str]:
    """Superlative -est: biggest->big, smallest->small, happiest->happy.

    Requires stem length ≥ 3 to prevent false positives.
    """
    if not w.endswith("est") or len(w) <= 4:
        return []
    results: list[str] = []
    if w.endswith("iest") and len(w) > 5:
        cand = w[:-4] + "y"
        if cand in coca_set and len(cand) >= 3:
            results.append(cand)
    base = w[:-3]
    if len(base) >= 3:  # guard: stem must be ≥3 chars
        if base in coca_set:
            results.append(base)
        if (base + "e") in coca_set:
            results.append(base + "e")
        if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
            single = base[:-1]
            if single in coca_set:
                results.append(single)
    return results


# ============================================================================
# Public API
# ============================================================================

def lemmatize(word: str, coca_set: set[str], sentence: str = "") -> str:
    """Comprehensive inflectional lemmatization with COCA validation.

    Args:
        word: The surface form to lemmatize.
        coca_set: COCA 20000 lemma set for validation.
        sentence: Optional sentence context for spaCy POS disambiguation.

    Strategy (in order):
    1. Contractions (text-cleaning artifacts)
    2. lemminflect — handles ALL irregular + regular inflections
       (replaces 236-entry hand-maintained IRREG dict)
    3. COCA check — if word is already a canonical lemma
    4. Regular inflection patterns (_try_ing, _try_ed, etc.)

    *No cross-POS conversion*: derivational adjectives stay as-is.
    """
    w = word.lower()

    # 1. Contractions (text-cleaning artifacts: "dont"→"do", "isnt"→"be")
    if w in _SPECIAL:
        lemma = _SPECIAL[w]
        if lemma in coca_set:
            return lemma

    # 2. lemminflect — comprehensive inflection handling
    #    Covers: irregular verbs (went→go, ran→run, bound→bind),
    #    irregular plurals (men→man, feet→foot),
    #    irregular comparatives (better→good, worse→bad),
    #    and regular inflections (walked→walk, cats→cat).
    #    Runs BEFORE COCA check so that words like "running"
    #    (in COCA as gerund) still reduce to "run".
    candidates = _try_lemminflect(w, coca_set)
    if candidates:
        return min(candidates, key=lambda x: (len(x), x))

    # 3. Superlative/comparative patterns — run BEFORE COCA check
    #    because words like "closest", "fastest" are in COCA but still
    #    should reduce to "close", "fast".  _try_est/_try_er have
    #    built-in COCA validation + minimum stem-length guard (≥3).
    est_candidates = _try_est(w, coca_set)
    if est_candidates:
        return min(est_candidates, key=lambda x: (len(x), x))
    er_candidates = _try_er(w, coca_set)
    if er_candidates:
        return min(er_candidates, key=lambda x: (len(x), x))

    # 4. Already in COCA — keep as-is (canonical lemma, no reduction needed)
    if w in coca_set:
        return w

    # 5. Other regular patterns — handle edge cases lemminflect misses
    #    (e.g. doubled consonants: crammed→cram, forsaken→forsake)
    reg_candidates: list[str] = []
    reg_candidates.extend(_try_ing(w, coca_set, sentence))
    reg_candidates.extend(_try_ed(w, coca_set, sentence))
    reg_candidates.extend(_try_s_es(w, coca_set))

    # Possessive -'s
    if w.endswith("'s") and len(w) > 3:
        cand = w[:-2]
        if cand in coca_set:
            reg_candidates.append(cand)

    if reg_candidates:
        return min(reg_candidates, key=lambda x: (len(x), x))

    # 5. No lemmatisation possible
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
