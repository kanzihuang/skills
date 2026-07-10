"""Inflectional lemmatization engine.

Canonical 5-step strategy (unified from resolve_lemma + lemmatize + lemmatize_word):

  1. Contractions → json_lemma explicit override (Claude-set, trusted).
  2. Suffix rules (-est/-er/-ier/-iest) with COCA gate.
  3. spaCy map primary source (POS-aware, pre-computed from full text).
  4. lemminflect multi-channel (VERB/NOUN/ADJ/ADV) with COCA gate.
  5. Nation word-family cross-validation — rejects cross-family misreductions.

No hardcoded word lists.  All false-positive paths (sacred→sacre, better→good,
tremendous→tremendou, happier→hap) are guarded by COCA + Nation gates.
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
# Lazy COCA loader (module-level cache — loaded once then shared)
# ============================================================================

_COCA_CACHE: set[str] | None = None


def _load_coca() -> set[str]:
    """Return cached COCA word set, loading from disk on first call."""
    global _COCA_CACHE
    if _COCA_CACHE is not None:
        return _COCA_CACHE
    try:
        from .coca import load_coca
        _COCA_CACHE = load_coca()
    except ImportError:
        _COCA_CACHE = set()
    return _COCA_CACHE


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
    #   - VBG + amod dependency → participial adjective, keep surface form
    #     (e.g. "the bewildering complexity" — not "bewilder")
    from collections import Counter
    votes: dict[str, Counter] = {}
    pos_counts: dict[str, Counter] = {}
    vbg_amod_forms: set[str] = set()

    chunk_size = 100_000
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        try:
            doc = nlp(chunk)
        except Exception:
            continue
        for token in doc:
            # Lowercase words tagged PROPN are spaCy misclassifications —
            # genuine proper nouns are always capitalised.  Skip them so
            # they don't pollute the map with surface-form-only entries
            # that block lemminflect from producing a valid reduction.
            if token.pos_ == "PROPN" and token.text[0].islower():
                continue
            surface = token.text.lower()
            lemma = token.lemma_.lower()
            pos = token.pos_
            if surface not in votes:
                votes[surface] = Counter()
                pos_counts[surface] = Counter()
            # VBG + amod = participial adjective modifying a noun.
            # Force lemma → surface so the map keeps it unreduced.
            if token.tag_ == "VBG" and token.dep_ == "amod":
                vbg_amod_forms.add(surface)
                votes[surface][surface] += 1
            else:
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

        # VBG-amod override: participial adjectives kept as surface form
        if surface in vbg_amod_forms:
            winner = surface

        result[surface] = winner  # always add — even canonical forms

    return result


# ============================================================================
# Public API — canonical lemmatize()
# ============================================================================

def lemmatize(
    word: str,
    coca_set: set[str] | None = None,
    spacy_map: dict[str, str] | None = None,
    json_lemma: str = "",
) -> str:
    """Canonical 5-step lemmatization engine.

    Args:
        word: Surface form to lemmatize.
        coca_set: COCA word set for validation.  Loaded lazily when None.
        spacy_map: Pre-computed ``{surface → lemma}`` from
                   :func:`build_spacy_map`.  Used as primary source
                   when available (POS-aware, zero false positives).
        json_lemma: Claude-set explicit lemma override.  When non-empty,
                    returned unconditionally (trusted).

    Strategy (in priority order):

    1. Contractions → explicit Claude override (trusted).
    2. Suffix rules (-est/-er/-ier/-iest) with COCA guard.
    3. spaCy map — POS-aware, handles irregulars and derived adjectives.
    4. lemminflect multi-channel (VERB/NOUN/ADJ/ADV) with COCA gate.
    5. Nation word-family cross-validation.
    """
    w = word.lower()

    # 1. Contractions (text-cleaning artifacts: "dont"→"do")
    if w in _CONTRACTIONS:
        return _CONTRACTIONS[w]

    # 2. Explicit override: Claude set lemma → trust it unconditionally.
    #    The quality checklist ensures Claude sets it correctly for
    #    derivational adjectives (blundering, accomplished, etc.).
    jl = json_lemma.strip().lower() if json_lemma else ""
    if jl:
        return jl

    # Resolve COCA set (lazy-load if not provided by caller)
    if coca_set is None:
        coca_set = _load_coca()

    # 3. Regular -est/-er/-ier/-iest patterns.
    #    Only apply when the word is NOT already in COCA, preventing false
    #    reductions like beer→bee, anger→ange, sacred→sacre.
    #    Candidate is stored in suffix_candidate and validated by later steps
    #    (spaCy map, Nation cross-validation) — no early return here.
    suffix_candidate = ""
    if w not in coca_set or w.endswith("est") or w.endswith("iest") or w.endswith("ier"):
        for sfx, slen in [("iest", 4), ("est", 3), ("ier", 3), ("er", 2)]:
            if w.endswith(sfx) and len(w) > slen + 1:
                stem = w[:-slen]
                if sfx.startswith("i"):
                    cand = stem + "y"          # happiest→happy, happier→happy
                else:
                    cand = stem                 # smallest→small
                    # Doubled consonant: biggest→big (only when the stem ends
                    # in CVC where C is the doubled consonant & not a true
                    # double-letter ending like -ll, -ss, -ff in the base).
                    if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiouyls":
                        cand2 = stem[:-1]
                        cand = cand2
                    # Dropped-e: closest→close (only if stem doesn't already
                    # look like a valid word, e.g. *small* from *smallest*).
                    if cand == stem and not (
                        len(stem) >= 2
                        and stem[-1] == stem[-2]
                        and stem[-1] not in "aeiouy"
                    ):
                        cand_e = stem + "e"
                        if cand_e in coca_set and cand_e != w:
                            cand = cand_e
                if cand != w and len(cand) < len(w):
                    # COCA plausibility gate: the candidate must be a
                    # recognizable English word.  Prevents false reductions
                    # like forever→forev (stem "forev" not in COCA) while
                    # allowing faster→fast, bigger→big, closest→close.
                    if coca_set and cand not in coca_set:
                        break
                    suffix_candidate = cand
                break

    # 4. spaCy map — primary source (POS-aware, zero false positives).
    #    When cand == w, spaCy has determined this is already a canonical
    #    form (e.g. "alluring" ADJ).  For common words (in COCA) return
    #    immediately — don't let the lemminflect fallback re-reduce a
    #    derived adjective to its verb stem.  For rare words not in COCA,
    #    fall through to lemminflect which may produce a valid reduction.
    if spacy_map and w in spacy_map:
        cand = spacy_map[w]
        if cand == w:
            if coca_set is None or w in coca_set:
                return w  # common word — trust spaCy
            # rare word — let lemminflect try (Step 5)
        elif coca_set and cand in coca_set:
            return cand

    # 5. lemminflect multi-channel fallback with COCA gate.
    try:
        from lemminflect import getLemma
    except ImportError:
        return jl or w

    reduced = suffix_candidate or w
    reduced_upos = ""  # track which POS channel produced the reduction

    # Agentive-noun guard: spaCy POS check for ADJ/ADV channels.
    # Nouns like walker, robber, baker are falsely reduced by lemminflect
    # ADJ/ADV channels (walker→walk, robber→rob).  Gate with spaCy POS:
    # skip ADJ/ADV reduction when the word is tagged as NOUN/PROPN.
    _is_noun = False
    if coca_set and w in coca_set:
        try:
            from .utils import _get_spacy
            nlp = _get_spacy()
            if nlp is not None:
                doc = nlp(w)
                if len(doc) > 0 and doc[0].pos_ in ("NOUN", "PROPN"):
                    _is_noun = True
        except Exception:
            pass

    for upos in ("VERB", "NOUN", "ADJ", "ADV"):
        # ADV channel gate: only trust -ly adverbs.  lemminflect ADV
        # produces false positives for non-ly words ("reflective"→"reflect",
        # "absurd"→"absur").  Applied at both levels — w in COCA and not.
        if upos == "ADV" and not (w.endswith("ly") and len(w) > 3):
            continue
        # ADJ/ADV agentive-noun gate: skip if spaCy says it's a noun
        if upos in ("ADJ", "ADV") and _is_noun:
            continue

        lemmas = getLemma(w, upos)
        if not lemmas:
            continue
        for lemma in lemmas:
            cand = lemma.lower()
            if cand == w:
                continue
            if w not in coca_set:
                # Word not in COCA — accept any valid reduction where lemma is in COCA
                if cand in coca_set:
                    if upos in ("VERB", "NOUN") or len(cand) < len(w):
                        reduced = cand
                        reduced_upos = upos
                        break
            else:
                # Both in COCA — accept reduction for VERB channel regardless
                # of length (had→have is longer), NOUN/ADJ/ADV requires shorter lemma
                if cand in coca_set:
                    if upos == "VERB" or len(cand) < len(w):
                        reduced = cand
                        reduced_upos = upos
                        break
        if reduced != w:
            break

    # 6. Nation word family cross-validation:
    #    If the reduced lemma belongs to a DIFFERENT word family than
    #    the original word, it's a cross-family misreduction
    #    (e.g. twined→twin, but Nation says twined belongs to twine).
    #    Does NOT catch intra-family reductions like blundering→blunder
    #    — Claude override + spaCy POS gate handle those.
    #
    #    Exception: when the VERB channel produces a reduction and both
    #    the word and the reduced lemma are in COCA, and spaCy confirms
    #    the word is not a noun, trust lemminflect over Nation.
    #    Nation homograph splits (e.g. loaf bread vs loaf idle) are data
    #    artifacts that should not override a high-confidence inflectional
    #    reduction.
    if reduced != w:
        try:
            from .coca import get_word_headword
            nation_head = get_word_headword(w)
            if nation_head:
                lemma_head = get_word_headword(reduced)
                if lemma_head and nation_head != lemma_head:
                    if (reduced_upos == "VERB" and not _is_noun
                            and coca_set and w in coca_set
                            and reduced in coca_set):
                        pass  # trust lemminflect VERB channel
                    else:
                        return w  # cross-family — keep original
        except ImportError:
            pass

    if reduced != w:
        return reduced
    return jl or w


# ============================================================================
# Thin helpers (backward-compatible)
# ============================================================================

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
