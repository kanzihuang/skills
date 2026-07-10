#!/usr/bin/env python3
"""Shared utilities for vocab-anki scripts.

Provides constants, filename helpers, lemmatization, and Edge TTS audio synthesis.

lemmatize_word() uses three-tier lemmatization:
  1. VERB + NOUN via lemminflect (inflectional: -ing, -ed, -s, -es)
  2. ADJ channel via lemminflect (comparatives/superlatives: -er, -est)
     Gated by spaCy POS — nouns (baker, walker) are NOT reduced.
  3. ADV channel via lemminflect — ONLY for -ly adverbs.
     Non-ly words are rejected because lemminflect ADV produces false
     positives: "absurd"→"absur", "reflective"→"reflect".
"""

import os
import re
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

from .config import EDGE_TTS_MAX_RETRIES, EDGE_TTS_RETRY_DELAY

# ---------------------------------------------------------------------------
# Filename utilities
# ---------------------------------------------------------------------------


def safe_filename(word: str) -> str:
    """Sanitize a word to a safe filesystem name (alphanumeric + underscore)."""
    safe = re.sub(r"[^a-zA-Z0-9]", "_", word)
    return safe.strip("_").lower() or "word"


# ---------------------------------------------------------------------------
# Quote normalization
# ---------------------------------------------------------------------------

# Curly / smart quote characters that may appear in source text (OCR) or
# translated Chinese text (DeepL output).  Normalising them to ASCII
# straight quotes prevents ``json.load()`` failures and
# ``check_step_completed.py`` rejections.
_CURLY_QUOTE_MAP_NORM = {
    "‘": "'",   # ' LEFT SINGLE
    "’": "'",   # ' RIGHT SINGLE
    "“": '"',   # " LEFT DOUBLE
    "”": '"',   # " RIGHT DOUBLE
    "＂": '"',   # " FULLWIDTH
}


def normalize_quotes(text: str) -> str:
    """Normalise Unicode curly/smart quotes to ASCII straight quotes.

    Covers typical OCR curly quotes (""'') and the fullwidth quotation
    mark (U+FF02).  Call this on *any* text that will enter the JSON
    output — source sentences, DeepL translations, and Claude-generated
    definitions.
    """
    result = text
    for curly, straight in _CURLY_QUOTE_MAP_NORM.items():
        result = result.replace(curly, straight)
    return result


# ---------------------------------------------------------------------------
# Fuzzy sentence matching
# ---------------------------------------------------------------------------


def build_sentence_regex(sentence: str) -> str:
    """Build a regex from sentence words joined by \\s+ for fuzzy matching.

    Strips punctuation from each word so "ephemeral," in the truncated
    sentence matches "ephemeral" in the source text. Handles newlines,
    straight/curly quotes, and minor punctuation differences.

    This is useful for Step 2B verification::

        import re
        from lib.utils import build_sentence_regex
        re.search(build_sentence_regex(truncated), raw_source_text)
    """
    import string
    _PUNCT = string.punctuation + '“”‘’…—–'
    words = []
    for w in sentence.split():
        w = w.strip(_PUNCT)
        if w:
            # Split on non-alpha to handle punctuation glued to the
            # next word (common OCR artifact).  E.g. "world.I" → two
            # tokens "world" + "I" joined by [^\w]*.
            parts = re.findall(r'[A-Za-z]+', w)
            words.extend(re.escape(p) for p in parts if p)
    # Join with [^\\w]* to swallow any non-word chars between words
    # (punctuation, whitespace, newlines, quotes).  \\s+ alone misses
    # "I, too" (comma after I) or "tenderness \\nand" (newline).
    return r'[^\w]*'.join(words)


# ---------------------------------------------------------------------------
# Lemmatization (inflectional only — derivational forms preserved)
# ---------------------------------------------------------------------------

_SPACY_NLP = None


def _get_spacy(enable_parser: bool = False):
    """Lazy-load spaCy en_core_web_sm (two-slot cache).

    By default disables parser and NER for speed (used as POS gate for
    ADJ channel in lemmatize_word).  Set *enable_parser=True* when
    dependency-parse signals are needed (e.g. _process_one_word).

    The two configurations are cached independently so a fast-path caller
    never poisons the full-pipeline cache.
    """
    global _SPACY_NLP
    if _SPACY_NLP is None:
        _SPACY_NLP = {}  # {enable_parser: nlp | False}
    if enable_parser not in _SPACY_NLP:
        try:
            import spacy

            if enable_parser:
                _SPACY_NLP[enable_parser] = spacy.load("en_core_web_sm")
            else:
                _SPACY_NLP[enable_parser] = spacy.load("en_core_web_sm", disable=["parser", "ner"])
        except Exception:
            _SPACY_NLP[enable_parser] = False
    nlp = _SPACY_NLP[enable_parser]
    return nlp if nlp is not False else None


def lemmatize_word(word: str) -> str:
    """Reduce an inflected word to its lemma (base form).

    Thin wrapper over the canonical :func:`lib.lemmatize.lemmatize`.
    Kept for backward compatibility with existing callers
    (filter_pipeline.py, audit_deck.py, validation in sync_anki.py).
    """
    from .lemmatize import lemmatize
    return lemmatize(word)


# ---------------------------------------------------------------------------
# Edge TTS (Microsoft Edge free TTS — works in China)
# ---------------------------------------------------------------------------


def _build_ssml(text: str, ipa: str | None = None, voice: str = "en-US-JennyNeural") -> str:
    """Build text for TTS.

    NOTE: edge_tts.Communicate internally applies escape() then wraps in its own
    <speak> SSML via mkssml(). Passing our own SSML here would be double-escaped
    and read as literal text (including the xmlns URL). Therefore we simply return
    plain text and let edge_tts handle SSML/prosody. The IPA parameter is kept for
    API compatibility but no longer used for audio synthesis.
    """
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if ipa:
        # IPA is still displayed on the Anki card; audio uses default TTS voice
        return escaped
    return escaped


async def _edge_tts_gen(text_or_ssml: str, voice: str) -> bytes:
    import edge_tts

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        communicate = edge_tts.Communicate(text_or_ssml, voice)
        await communicate.save(tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


def edge_tts_bytes(
    text: str, ipa: str | None = None, voice: str = "en-US-JennyNeural"
) -> bytes | None:
    """Generate TTS audio bytes using Edge TTS.

    IPA parameter is kept for API compatibility; displayed on card but NOT used
    for audio synthesis (SSML <phoneme> not supported by edge_tts library —
    see _build_ssml docstring for details).
    Retries on transient failure (up to EDGE_TTS_MAX_RETRIES extra attempts).
    Returns None on persistent failure.
    """
    import asyncio
    import threading

    # Cache one event loop per thread (ThreadPoolExecutor workers).
    # Avoids creating+destroying a loop per asyncio.run() call
    # (~600 cycles for 300 words × 2 audio files → ~3-6 s overhead).
    _tl = threading.local()
    if not hasattr(_tl, "loop"):
        _tl.loop = asyncio.new_event_loop()

    ssml = _build_ssml(text, ipa, voice)
    for attempt in range(EDGE_TTS_MAX_RETRIES + 1):
        try:
            result = _tl.loop.run_until_complete(_edge_tts_gen(ssml, voice))
            if result:
                return result
        except Exception:
            pass
        if attempt < EDGE_TTS_MAX_RETRIES:
            time.sleep(EDGE_TTS_RETRY_DELAY)
    return None


def edge_tts_file(
    text: str,
    dest_path: str,
    ipa: str | None = None,
    voice: str = "en-US-JennyNeural",
) -> bool:
    """Generate TTS audio to a file using Edge TTS.

    IPA parameter is kept for API compatibility; displayed on card but NOT used
    for audio synthesis (SSML <phoneme> not supported by edge_tts library —
    see _build_ssml docstring for details).
    Retries on transient failure (up to EDGE_TTS_MAX_RETRIES extra attempts).
    Returns True on success.
    """
    import asyncio
    import threading

    _tl = threading.local()
    if not hasattr(_tl, "loop"):
        _tl.loop = asyncio.new_event_loop()

    ssml = _build_ssml(text, ipa, voice)

    async def _gen() -> bool:
        import edge_tts

        try:
            communicate = edge_tts.Communicate(ssml, voice)
            await communicate.save(dest_path)
            return True
        except Exception:
            return False

    for attempt in range(EDGE_TTS_MAX_RETRIES + 1):
        try:
            if _tl.loop.run_until_complete(_gen()):
                return True
        except Exception:
            pass
        if attempt < EDGE_TTS_MAX_RETRIES:
            time.sleep(EDGE_TTS_RETRY_DELAY)
    return False


# ---------------------------------------------------------------------------
# Progress output (text-only, no graphical bar — Claude Code can't do \r)
# ---------------------------------------------------------------------------

def print_progress(i: int, total: int, label: str = ""):
    """Print a text progress line.

    Uses \\r for in-place update when stdout is a real TTY; appends a newline
    otherwise (piped / captured / Claude Code).  Plain text format — no
    graphical bar characters — so output reads cleanly in both environments.

    Example output:
      13/64  comfort  audio: word✓, sent✓
    """
    line = f"  {i}/{total}"
    if label:
        line += f"  {label}"
    if sys.stdout.isatty():
        print("\r" + line, end="", flush=True)
    else:
        print(line, flush=True)


def validate_plain_text(text: str, source: str = "source text") -> None:
    """Check that *text* is plain text, not an HTML wrapper.

    Scans the first 500 characters for common HTML signatures
    (``<!doctype html>``, ``<html>``, ``<head>``, ``<body>``,
    ``<meta>``, ``<title>``).  Calls ``sys.exit(1)`` with a
    clear error message when HTML is detected — the caller does
    not need to check a return value.

    This is a mechanical defence-in-depth guard.  The same check
    is also documented as a procedural step in SHARED_WORKFLOW.md
    (Step 2A-0 / 2A-a/b), but embedding it in Python ensures an
    HTML-wrapped file can never be silently processed as text.
    """
    sample = text[:500].lstrip().casefold()
    for sig in ("<!doctype html", "<html", "<head", "<body", "<meta", "<title"):
        if sig in sample:
            print(
                f"ERROR: {source} appears to be HTML (found '{sig}'). "
                f"Use a plain-text version of the book. "
                f"For Internet Archive, use the /download/ path, "
                f"not /stream/.",
                file=sys.stderr,
            )
            sys.exit(1)
