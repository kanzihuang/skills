"""COCA frequency lookup.

Shared library for word frequency operations using a single COCA word-form
frequency list.

Provides three public functions:
    load_coca() -> set[str]              -- load the COCA word set for membership checks
    in_coca(word, coca_set) -> tuple[bool, str]  -- three-tier lookup
    load_freq_ranked(top_n) -> list[str]  -- load top-N words by frequency rank
"""

from __future__ import annotations

import os
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "coca_freq.txt"
)

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_coca_cache: Optional[set[str]] = None
_freq_cache: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_coca() -> set[str]:
    """Load the COCA word set (cached after first call).

    Reads from the single frequency-ranked word list, building a set for
    O(1) membership checks.  Line order (frequency rank) is irrelevant for
    set operations.
    """
    global _coca_cache
    if _coca_cache is None:
        words: set[str] = set()
        with open(_DATA_PATH, encoding="utf-8") as fh:
            for line in fh:
                w = line.strip().lower()
                if w:
                    words.add(w)
        _coca_cache = words
    return _coca_cache


def load_freq_ranked(top_n: int | None = None) -> list[str]:
    """Load the top-N most frequent words, ranked by frequency (cached).

    Line order in the data file = frequency rank (line 1 = highest freq).
    Returns an ordered list so that ``[:top_n]`` slicing yields the most
    common N words.

    Args:
        top_n: Number of top-frequency words to return (None = all).
    """
    global _freq_cache
    if _freq_cache is None:
        words: list[str] = []
        with open(_DATA_PATH, encoding="utf-8") as fh:
            for line in fh:
                w = line.strip().lower()
                if w:
                    words.append(w)
        _freq_cache = words
    if top_n is not None:
        return _freq_cache[:top_n]
    return _freq_cache


def in_coca(word: str, coca_lemmas: set[str] | None = None) -> tuple[bool, str]:
    """Check whether *word* (or its lemma form) is in the COCA frequency list.

    Three-tier lookup strategy:

    Tier 1  direct set lookup (O(1)) — covers most words
    Tier 2  lemminflect lemmatisation — handles inflected forms (runs→run)
    Tier 3  suffix-stripping fallback — handles derivational forms that
            COCA lists only by their base (indulgently→indulgent,
            resentfulness→resentful)

    Tiers 2–3 serve as a **derivational normalisation layer**.  The
    pipeline's Step 1d ``lemmatize_word()`` intentionally only handles
    inflectional forms (pondered→ponder), leaving derivational forms
    untouched.  This function bridges the gap: COCA contains base lemmas
    (indulgent, resentful) but not all derivational variants (indulgently,
    resentfulness).

    Args:
        word: The word to check (any inflected or derived form).
        coca_lemmas: Pre-loaded lemma set.  Loaded automatically if None.

    Returns:
        ``(in_list, detail)`` — *detail* explains the match or reason.
    """
    if coca_lemmas is None:
        coca_lemmas = load_coca()

    w = word.strip().lower()
    if not w:
        return False, "empty word"

    # Tier 1: direct lookup
    if w in coca_lemmas:
        return True, w

    # Tier 2: lemminflect inflectional reduction
    # Only accept a lemma that is strictly shorter (true suffix removal).
    # Same-length mappings (abode→abide, ran→run) are irregular stem
    # changes that lemminflect cannot verify without POS context; same-length
    # VERB mappings to unrelated lemmas cause false positives (abode n.住所
    # → abide v.忍受).  Same-length irregular verbs (ran→run, sat→sit) are
    # basic vocabulary users rarely highlight.
    try:
        import lemminflect  # type: ignore

        for pos in ("VERB", "NOUN", "ADJ", "ADV"):
            lemmas = lemminflect.getLemma(w, upos=pos)
            for lemma in lemmas:
                l = lemma.lower()
                if len(l) < len(w) and l in coca_lemmas:
                    return True, f"{w} -> {l}"
    except ImportError:
        pass

    # Tier 3: derivational suffix stripping
    _SUFFIX_MAP = [
        ("fulness", "ful"),   # resentfulness → resentful
        ("fully", "ful"),     # beautifully → beautiful
        ("iness", "y"),       # happiness → happy
        ("liness", "ly"),     # friendliness → friendly
        ("ment", ""),         # encouragement → encourage
        ("ness", ""),         # sadness → sad
        ("ly", ""),           # indulgently → indulgent
        ("ing", ""),          # interesting → interest
        ("ings", ""),         # happenings → happening
        ("ed", ""),           # walked → walk
        ("es", ""),           # boxes → box
        ("s", ""),            # cats → cat
    ]
    for suffix, replacement in _SUFFIX_MAP:
        if w.endswith(suffix) and len(w) - len(suffix) >= 2:
            stem = w[: -len(suffix)] + replacement
            if stem in coca_lemmas:
                return True, f"{w} -> {stem}"
            # also try appending 'e' (e.g. hoping → hope)
            stem_e = stem + "e"
            if stem_e in coca_lemmas:
                return True, f"{w} -> {stem_e}"

    return False, f"{w} not in COCA"
