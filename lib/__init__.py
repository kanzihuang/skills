"""Shared library for English vocabulary processing.

Provides:
    load_coca()              -- load COCA word set (for membership checks)
    in_coca(word, coca_set)  -- three-tier COCA frequency lookup
    load_freq_ranked(top_n)  -- load top-N words by frequency rank
    lemmatize(word, coca_set) -- comprehensive inflectional lemmatization
    lemmatize_conservative(word) -- VERB/NOUN-only via lemminflect
    IRREG                     -- irregular form dictionary
"""

from .coca import load_coca, in_coca, load_freq_ranked
from .lemmatize import lemmatize, lemmatize_conservative, IRREG

__all__ = [
    "load_coca",
    "in_coca",
    "load_freq_ranked",
    "lemmatize",
    "lemmatize_conservative",
    "IRREG",
]
