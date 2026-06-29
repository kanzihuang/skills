#!/usr/bin/env python3
"""Extract a COCA 20000 filtered word list from raw English book text.

Part of the vocab-list skill.  Imports shared lemmatization + COCA logic
from the repo-level lib/ package.

Usage
-----
    # Basic extraction:
    python3 extract_vocab.py < /tmp/book.txt

    # Clean headers/footers first, then extract:
    python3 extract_vocab.py --clean < /tmp/book_raw.txt

    # Exclude top-1000 most frequent words (too basic):
    python3 extract_vocab.py --exclude-basic 1000 < book.txt

    # Only keep words in Google 10K rank range 3001-10000 (mid-frequency):
    python3 extract_vocab.py --basic-range 3001-10000 < book.txt

    # Combine: exclude top-3000 AND only keep ranks 3001-10000:
    python3 extract_vocab.py --exclude-basic 3000 --basic-range 3001-10000 < book.txt

Output
------
    [STATS]     one line:  Raw: N | COCA: N | Excluded: N
    ---COCA---
    word1
    word2
    ...
    ---EXCLUDED---
    word1
    word2
    ...
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# -- Add repo root to path so we can import lib/ ---------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib import load_coca, lemmatize, load_basic_words  # noqa: E402


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

# Regex patterns to strip from raw web-sourced text.
_CLEAN_PATTERNS: list[str] = [
    r"=== CHAPTER \d+ ===",
    r"Table of Contents >>.*?>>",
    r"HTML layout and style by Stephen Thomas.*?Learning\.",
    r"For English Language Learners.*?by Antoine de Saint-Exupéry",
    r"404 Not Found.*?\n",
    r"\bChapter \d+\b",
]


def clean_text(text: str) -> str:
    """Strip common web-scraping artifacts from raw book text."""
    for pat in _CLEAN_PATTERNS:
        text = re.sub(pat, " ", text)
    return text


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_vocab(text: str, coca_set: set[str]) -> tuple[list[str], list[str]]:
    """Extract COCA-filtered and excluded word lists from raw text.

    Returns (coca_words, excluded_words), both sorted and deduplicated.
    """
    # Tokenize: alphabetic sequences, min 2 characters
    words: list[str] = re.findall(r"[a-zA-Z]{2,}", text)
    unique = sorted(set(w.lower() for w in words))

    coca_words: list[str] = []
    excluded: list[str] = []

    for w in unique:
        lemma = lemmatize(w, coca_set)
        if lemma in coca_set:
            coca_words.append(lemma)
        else:
            excluded.append(w)

    # Deduplicate (lemmatization may map different surface forms to same lemma)
    coca_words = sorted(set(coca_words))
    excluded = sorted(set(excluded))

    return coca_words, excluded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    text = sys.stdin.read()

    if "--clean" in sys.argv:
        text = clean_text(text)

    if not text.strip():
        print("Error: no text provided on stdin", file=sys.stderr)
        sys.exit(1)

    # Parse --exclude-basic N  (exclude top-N most frequent words)
    # Parse --basic-range MIN-MAX  (keep only words in this Google 10K rank range)
    exclude_basic = 0
    basic_min = 0       # 0 = no lower bound
    basic_max = 0       # 0 = no upper bound
    for i, arg in enumerate(sys.argv):
        if arg == "--exclude-basic" and i + 1 < len(sys.argv):
            try:
                exclude_basic = int(sys.argv[i + 1])
            except ValueError:
                print(f"Error: --exclude-basic requires a number, got '{sys.argv[i+1]}'",
                      file=sys.stderr)
                sys.exit(1)
        if arg == "--basic-range" and i + 1 < len(sys.argv):
            parts = sys.argv[i + 1].split("-")
            if len(parts) == 2:
                try:
                    basic_min = int(parts[0])
                    basic_max = int(parts[1])
                except ValueError:
                    print(f"Error: --basic-range requires MIN-MAX, got '{sys.argv[i+1]}'",
                          file=sys.stderr)
                    sys.exit(1)

    coca_set = load_coca()
    coca_words, excluded = extract_vocab(text, coca_set)

    # Apply basic-words filter if requested
    basic_excluded = 0
    basic_out_of_range = 0
    if exclude_basic > 0 or basic_max > 0:
        all_10k = load_basic_words(10000)  # ordered list, rank 1 = most frequent
        if exclude_basic > 0:
            basic_set = set(all_10k[:exclude_basic])  # top-N
            basic_excluded = len(set(coca_words) & basic_set)
            coca_words = [w for w in coca_words if w not in basic_set]
        if basic_min > 0 or basic_max > 0:
            lo = max(basic_min, 1)
            hi = min(basic_max, len(all_10k)) if basic_max else len(all_10k)
            in_range = set(all_10k[lo-1:hi])  # ranks lo..hi
            before = len(coca_words)
            coca_words = [w for w in coca_words if w in in_range]
            basic_out_of_range = before - len(coca_words)

    # Count raw unique words (before lemmatization)
    raw_count = len(set(re.findall(r"[a-zA-Z]{2,}", text.lower())))
    parts = [f"Raw: {raw_count}", f"COCA: {len(coca_words)}", f"Excluded: {len(excluded)}"]
    if exclude_basic:
        parts.append(f"Basic-filtered: {basic_excluded}")
    if basic_min or basic_max:
        parts.append(f"Out-of-range: {basic_out_of_range}")
    print(" | ".join(parts))
    print("---COCA---")
    for w in coca_words:
        print(w)
    print("---EXCLUDED---")
    for w in excluded:
        print(w)


if __name__ == "__main__":
    main()
