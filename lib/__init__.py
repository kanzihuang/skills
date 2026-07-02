"""Shared library for English vocabulary processing.

Provides:
    load_cora()              -- load COCA word set (for membership checks)
    in_coca(word, coca_set)  -- three-tier COCA frequency lookup
    load_freq_ranked(top_n)  -- load top-N words by frequency rank
    lemmatize(word, coca_set) -- comprehensive inflectional lemmatization
    lemmatize_conservative(word) -- VERB/NOUN-only via lemminflect
    build_spacy_map(text)    -- one-time spaCy parse of full text
    AnkiConnect / AnkiConnectError -- AnkiConnect JSON-RPC client
    lemmatize_word(word)     -- three-tier lemmatization (legacy, prefer lemmatize)
    safe_filename(word)      -- sanitize string to alphanumeric + underscore
    edge_tts_bytes(text, ...) -- async Edge TTS generation
    print_progress(i, total, label) -- text progress output
"""

from .coca import load_coca, in_coca, load_freq_ranked
from .lemmatize import lemmatize, lemmatize_conservative, build_spacy_map
from .ankiconnect import AnkiConnect, AnkiConnectError
from .utils import lemmatize_word, safe_filename, edge_tts_bytes, print_progress

__all__ = [
    "load_coca",
    "in_coca",
    "load_freq_ranked",
    "lemmatize",
    "lemmatize_conservative",
    "build_spacy_map",
    "AnkiConnect",
    "AnkiConnectError",
    "lemmatize_word",
    "safe_filename",
    "edge_tts_bytes",
    "print_progress",
]
