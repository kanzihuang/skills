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


def _get_spacy():
    """Lazy-load spaCy en_core_web_sm (used as POS gate for ADJ channel)."""
    global _SPACY_NLP
    if _SPACY_NLP is None:
        try:
            import spacy

            _SPACY_NLP = spacy.load("en_core_web_sm", disable=["parser", "ner"])
        except Exception:
            _SPACY_NLP = False
    return _SPACY_NLP if _SPACY_NLP is not False else None


def lemmatize_word(word: str) -> str:
    """Reduce an inflected word to its lemma (base form).

    Three-tier strategy:
      1. VERB (covers -ing, -ed, -s) then NOUN (plurals) via lemminflect.
      2. ADJ + ADV channels for comparative/superlative forms (-er, -est),
         gated by spaCy POS: only reduced if spaCy does NOT tag the word
         as NOUN/PROPN.  This prevents agentive nouns (baker, walker,
         robber) from being falsely reduced while allowing genuine
         comparatives (higher→high, faster→fast).
      3. Falls back to the original word.

    Only accepts a lemma strictly shorter than the input word to avoid
    same-length cross-POS errors (abode n.→abide v.).
    Same-length irregulars (ran→run) remain unhandled — basic vocabulary
    that rarely appears as highlighted words.

    Returns the lemma, or the original word if no change.
    """
    import lemminflect

    w = word.strip().lower()

    # Tier 1: VERB (covers -ing, -ed, -s, -es), then NOUN (plurals)
    for pos in ("VERB", "NOUN"):
        lemmas = lemminflect.getLemma(w, pos)
        if lemmas:
            lemma = lemmas[0].lower()
            if lemma != w and len(lemma) < len(w):
                return lemma

    # Tier 2: ADJ/ADV — comparatives and superlatives (-er, -est)
    # Gate with spaCy POS: skip if the word is a noun (baker, walker,
    # robber) rather than a comparative adjective.
    nlp = _get_spacy()
    if nlp is not None:
        try:
            doc = nlp(w)
            if len(doc) > 0 and doc[0].pos_ in ("NOUN", "PROPN"):
                return w  # noun — don't apply ADJ reduction
        except Exception:
            pass

    # ADJ channel: comparatives (-er) and superlatives (-est)
    lemmas = lemminflect.getLemma(w, "ADJ")
    if lemmas:
        lemma = lemmas[0].lower()
        if lemma != w and len(lemma) < len(w):
            return lemma

    # ADV channel: ONLY trust for -ly adverbs.
    # lemminflect ADV channel produces false positives for non-adverb
    # words: "absurd"→"absur" (treats 'd' as comparative suffix),
    # "reflective"→"reflect" (treats 'ive' as adverb suffix).
    # Genuine adverb reductions (slowly→slow, happily→happy) all end
    # in -ly.  Reject any ADV reduction where the input doesn't end in
    # -ly to prevent false positives.
    if w.endswith("ly") and len(w) > 3:
        lemmas = lemminflect.getLemma(w, "ADV")
        if lemmas:
            lemma = lemmas[0].lower()
            if lemma != w and len(lemma) < len(w):
                return lemma

    return w


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
