"""COCA 20000 frequency lookup.

Shared library for checking whether a word (or its lemma) is in the
COCA 20000 most-frequent-English-words list.

Provides two public functions:
    load_coca() -> set[str]   -- load and cache the COCA lemma set
    in_coca(word, coca_set) -> bool  -- three-tier lookup
"""

from pathlib import Path
from typing import Optional

_COCA_CACHE: Optional[set[str]] = None
_COCA_PATH = Path(__file__).resolve().parent / "data" / "coca_20000.txt"

_GOOGLE_10K_CACHE: Optional[list[str]] = None
_GOOGLE_10K_PATH = Path(__file__).resolve().parent / "data" / "google_10k.txt"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_coca() -> set[str]:
    """Load COCA 20000 lemma set (cached after first call)."""
    global _COCA_CACHE
    if _COCA_CACHE is None:
        lemmas: set[str] = set()
        with open(_COCA_PATH, encoding="utf-8") as fh:
            for line in fh:
                word = line.strip().lower()
                if word:
                    lemmas.add(word)
        _COCA_CACHE = lemmas
    return _COCA_CACHE


def load_basic_words(top_n: int) -> list[str]:
    """Load the top-N most frequent English words from Google 10K.

    These are the most common words in English (the, of, and, to, a, …),
    ranked by frequency.  Returns an ordered list (rank 1 = most frequent).

    Used to exclude trivial vocabulary from word lists.

    Args:
        top_n: Number of top-frequency words to include (1–10000).
    """
    global _GOOGLE_10K_CACHE
    if _GOOGLE_10K_CACHE is None:
        words: list[str] = []
        with open(_GOOGLE_10K_PATH, encoding="utf-8") as fh:
            for line in fh:
                w = line.strip().lower()
                if w:
                    words.append(w)
        _GOOGLE_10K_CACHE = words
    return _GOOGLE_10K_CACHE[:top_n]


def in_coca(word: str, coca_set: set[str]) -> bool:
    """Three-tier COCA lookup.

    Tier 1 -- direct set lookup (O(1))
    Tier 2 -- lemminflect derivational normalisation (len(lemma) < len(word))
    Tier 3 -- suffix-stripping fallback
    """
    w = word.lower()

    # Tier 1: direct lookup
    if w in coca_set:
        return True

    # Tier 2: lemminflect inflectional reduction
    try:
        from lemminflect import getLemma
    except ImportError:
        return False

    for upos in ("NOUN", "VERB", "ADJ", "ADV"):
        lemmas = getLemma(w, upos)
        if not lemmas:
            continue
        for lemma in lemmas:
            if lemma == w:
                continue
            # Only accept strictly-shorter lemma (true inflectional reduction).
            # This avoids cross-POS false positives like abode n. -> abide v.
            if len(lemma) < len(w) and lemma in coca_set:
                return True

    # Tier 3: derivational suffix stripping
    _SUFFIX_MAP = [
        ("fulness", "ful"),
        ("fully", "ful"),
        ("iness", "y"),
        ("liness", "ly"),
        ("ment", ""),
        ("ness", ""),
        ("ly", ""),
        ("ing", ""),
        ("ings", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
    ]
    for sfx, repl in _SUFFIX_MAP:
        if w.endswith(sfx) and len(w) - len(sfx) >= 2:
            stem = w[: -len(sfx)] + repl
            if stem in coca_set:
                return True
            # also try appending 'e' (e.g. hoping -> hope)
            stem_e = stem + "e"
            if stem_e in coca_set:
                return True

    return False
