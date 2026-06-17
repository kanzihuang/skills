"""COCA 20000 word frequency check.

Loads the COCA 20000 lemma list and provides a lookup function that checks
whether a given word (or its lemma form) is among the top 20,000 most
frequent English words according to the Corpus of Contemporary American English.

Usage:
    from coca_lookup import load_coca, in_coca
    coca = load_coca()
    if in_coca("pondered", coca):
        print("in COCA 20000")
"""

import os

# Path to the COCA word list, relative to this file
_LIST_PATH = os.path.join(os.path.dirname(__file__), "coca_20000.txt")

# Cache the loaded set to avoid re-reading
_coca_cache: set[str] | None = None


def load_coca() -> set[str]:
    """Load COCA 20000 lemmas into a set (lowercase). Cached after first call."""
    global _coca_cache
    if _coca_cache is not None:
        return _coca_cache
    lemmas: set[str] = set()
    if os.path.exists(_LIST_PATH):
        with open(_LIST_PATH, encoding="utf-8") as f:
            for line in f:
                w = line.strip().lower()
                if w:
                    lemmas.add(w)
    _coca_cache = lemmas
    return lemmas


def in_coca(word: str, coca_lemmas: set[str] | None = None) -> tuple[bool, str]:
    """Check if a word (or its lemma form) is in the COCA 20000 list.

    Args:
        word: The word to check (can be any inflected form).
        coca_lemmas: Pre-loaded lemma set. If None, loads automatically.

    Returns:
        (in_list: bool, detail: str) — detail explains the match or reason.
    """
    if coca_lemmas is None:
        coca_lemmas = load_coca()

    w = word.strip().lower()
    if not w:
        return False, "empty word"

    # Direct match
    if w in coca_lemmas:
        return True, f"{w}"

    # Try lemmatization
    try:
        import lemminflect  # type: ignore

        for pos in ("VERB", "NOUN", "ADJ", "ADV"):
            lemmas = lemminflect.getLemma(w, upos=pos)
            for lemma in lemmas:
                l = lemma.lower()
                if l in coca_lemmas:
                    return True, f"{w} -> {l}"
    except ImportError:
        pass

    # Suffix-stripping fallback for forms lemminflect misses
    # (e.g. "indulgently" -> "indulgent", "resentfulness" -> "resentful")
    suffix_map = [
        ("fulness", "ful"),  # resentfulness -> resentful
        ("fully", "ful"),    # beautifully -> beautiful
        ("iness", "y"),      # happiness -> happy
        ("liness", "ly"),    # friendliness -> friendly
        ("ment", ""),        # encouragement -> encourage
        ("ness", ""),        # sadness -> sad
        ("ly", ""),          # indulgently -> indulgent
        ("ing", ""),         # interesting -> interest
        ("ings", ""),        # happenings -> happening
        ("ed", ""),          # walked -> walk
        ("es", ""),          # boxes -> box
        ("s", ""),           # cats -> cat
    ]
    for suffix, replacement in suffix_map:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            stem = w[:-len(suffix)] + replacement
            if stem in coca_lemmas:
                return True, f"{w} -> {stem}"
            # Also try stem + "e" (e.g. "indulgently" -> "indulgente" no, but
            # "hoping" -> "hope")
            stem_e = stem + "e"
            if stem_e in coca_lemmas:
                return True, f"{w} -> {stem_e}"

    return False, f"{w} not in COCA 20000"
