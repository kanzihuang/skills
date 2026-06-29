"""Shared library for English vocabulary processing.

Provides:
    load_coca()            -- load COCA 20000 lemma set
    in_coca(word, coca_set) -- three-tier COCA frequency lookup
    lemmatize(word, coca_set) -- comprehensive inflectional lemmatization
    lemmatize_conservative(word) -- VERB/NOUN-only via lemminflect
    IRREG                   -- irregular form dictionary
"""

from .coca import load_coca, in_coca, load_basic_words
from .lemmatize import lemmatize, lemmatize_conservative, IRREG

__all__ = [
    "load_coca",
    "in_coca",
    "load_basic_words",
    "lemmatize",
    "lemmatize_conservative",
    "IRREG",
]
