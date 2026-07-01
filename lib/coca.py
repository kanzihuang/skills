"""BNC/COCA word family frequency lookup (Nation, 2017).

Replaces the corrupted word-form frequency file with Paul Nation's
academically validated BNC/COCA word family lists (25 levels of 1000
word families each, Bauer & Nation Level 6 affix criteria).

Data format (Range program):
    HEADWORD FREQ
    \\tMEMBER FREQ
    \\tMEMBER FREQ

Provides:
    load_coca() -> set[str]              -- all word forms in Nation lists
    in_coca(word, set) -> (bool, str)    -- three-tier lookup
    load_freq_ranked(top_n) -> list[str] -- headwords in level order
    get_word_level(word) -> int | None   -- level 1-25
    get_word_headword(word) -> str | None -- family headword
    load_level_range(lo, hi) -> set[str] -- all word forms in levels lo-hi

Reference:
    Nation, I.S.P. (2017). The BNC/COCA Level 6 word family lists
    (Version 1.0.0) [Data file]. Available from
    http://www.victoria.ac.nz/lals/staff/paul-nation.aspx
"""

from __future__ import annotations

import os
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "bnc_coca"
)

_NUM_LEVELS = 25  # basewrd1.txt through basewrd25.txt

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_nation_set_cache: Optional[set[str]] = None       # all word forms (levels 1-25)
_nation_level_cache: Optional[dict[str, int]] = None  # word → level (1-25)
_nation_headword_cache: Optional[dict[str, str]] = None  # word → headword
_nation_headwords_cache: Optional[list[str]] = None   # headwords in level order


# ---------------------------------------------------------------------------
# Internal: data loading
# ---------------------------------------------------------------------------

def _load_nation_data() -> None:
    """Load all 25 BNC/COCA word family files into global caches."""
    global _nation_set_cache, _nation_level_cache
    global _nation_headword_cache, _nation_headwords_cache

    words: set[str] = set()
    level_map: dict[str, int] = {}
    headword_map: dict[str, str] = {}
    headwords: list[str] = []

    for level in range(1, _NUM_LEVELS + 1):
        path = os.path.join(_DATA_DIR, f"basewrd{level}.txt")
        if not os.path.isfile(path):
            print(f"WARNING: {path} not found, skipping level {level}",
                  file=sys.stderr)
            continue

        with open(path, encoding="utf-8", errors="replace") as fh:
            current_headword: str | None = None
            for line in fh:
                line = line.rstrip("\n\r")
                if not line:
                    continue

                # Split: first token = word, rest = frequency number (discard)
                parts = line.split(" ", 1)
                word = parts[0].strip().lower()
                if not word:
                    continue

                if line.startswith("\t"):
                    # Family member
                    if current_headword is not None:
                        words.add(word)
                        headword_map[word] = current_headword
                        # First occurrence wins = lowest/most-frequent level
                        if word not in level_map:
                            level_map[word] = level
                else:
                    # Headword — starts a new family
                    current_headword = word
                    words.add(word)
                    headword_map[word] = word
                    headwords.append(word)
                    # First occurrence wins
                    if word not in level_map:
                        level_map[word] = level

    if not words:
        print("ERROR: No BNC/COCA word family data found. "
              f"Expected files in {_DATA_DIR}/basewrd1.txt–basewrd{_NUM_LEVELS}.txt",
              file=sys.stderr)

    _nation_set_cache = words
    _nation_level_cache = level_map
    _nation_headword_cache = headword_map
    _nation_headwords_cache = headwords


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_coca() -> set[str]:
    """Return the set of all word forms in the Nation BNC/COCA lists.

    Covers all 25 levels (levels 1-25), includes both headwords and
    family members.  Cached after first call.
    """
    global _nation_set_cache
    if _nation_set_cache is None:
        _load_nation_data()
    return _nation_set_cache  # type: ignore[return-value]


def load_freq_ranked(top_n: int | None = None) -> list[str]:
    """Return headwords in level order (level 1 first, then level 2, ...).

    Each headword represents one word family.  The list preserves the
    order of families within each level as they appear in the basewrd
    files (alphabetical within level).

    Args:
        top_n: Number of headwords to return (None = all).
    """
    global _nation_headwords_cache
    if _nation_headwords_cache is None:
        _load_nation_data()
    if top_n is not None:
        return _nation_headwords_cache[:top_n]  # type: ignore[index]
    return list(_nation_headwords_cache)  # type: ignore[arg-type]


def in_coca(word: str, coca_lemmas: set[str] | None = None) -> tuple[bool, str]:
    """Check whether *word* (or its lemma form) is in the Nation lists.

    Three-tier lookup strategy (unchanged from coca_freq.txt era,
    now operating on the Nation word family set):

    Tier 1  direct set lookup (O(1))
    Tier 2  lemminflect lemmatisation (handles inflected forms)
    Tier 3  suffix-stripping fallback (handles derivational forms)

    Args:
        word: The word to check (any inflected or derived form).
        coca_lemmas: Pre-loaded set.  Loaded automatically if None.

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

    return False, f"{w} not in BNC/COCA"


def get_word_level(word: str) -> int | None:
    """Return the BNC/COCA word family level (1-25) for *word*.

    Level 1 = most frequent 1000 word families.
    Level 25 = least frequent 1000 word families.

    Returns None if the word is not in any family list.
    """
    global _nation_level_cache
    if _nation_level_cache is None:
        _load_nation_data()
    w = word.strip().lower()
    if not w:
        return None
    return _nation_level_cache.get(w)


def get_word_headword(word: str) -> str | None:
    """Return the family headword for *word* in the Nation BNC/COCA lists.

    Both headwords and family members return the headword.
    Returns None if the word is not in any family list.
    """
    global _nation_headword_cache
    if _nation_headword_cache is None:
        _load_nation_data()
    w = word.strip().lower()
    if not w:
        return None
    return _nation_headword_cache.get(w)


def load_level_range(lo: int = 1, hi: int = 25) -> set[str]:
    """Return all word forms in family levels *lo* through *hi* (inclusive).

    Args:
        lo: Minimum level (1-25).  Default 1.
        hi: Maximum level (1-25).  Default 25.

    Returns:
        Set of all word forms (lowercased) in the specified level range.
    """
    global _nation_level_cache
    if _nation_level_cache is None:
        _load_nation_data()
    lo = max(1, min(lo, _NUM_LEVELS))
    hi = max(1, min(hi, _NUM_LEVELS))
    if lo > hi:
        return set()
    return {word for word, lvl in _nation_level_cache.items()
            if lo <= lvl <= hi}
