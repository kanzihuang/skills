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

EDGE_TTS_MAX_RETRIES = 2  # Retry Edge TTS up to 2 extra times (3 total) on transient failure
EDGE_TTS_RETRY_DELAY = 0.75  # seconds between Edge TTS retries

# ---------------------------------------------------------------------------
# Filename utilities
# ---------------------------------------------------------------------------


def safe_filename(word: str) -> str:
    """Sanitize a word to a safe filesystem name (alphanumeric + underscore)."""
    safe = re.sub(r"[^a-zA-Z0-9]", "_", word)
    return safe.strip("_").lower() or "word"


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

    ssml = _build_ssml(text, ipa, voice)
    for attempt in range(EDGE_TTS_MAX_RETRIES + 1):
        try:
            result = asyncio.run(_edge_tts_gen(ssml, voice))
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
            if asyncio.run(_gen()):
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
