#!/usr/bin/env python3
"""Shared utilities for vocab-anki scripts.

Provides constants, filename helpers, lemmatization, and Edge TTS audio synthesis.
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


# Valid English inflectional suffixes for sanity-checking lemmatization results
_VALID_INFLECTIONS = frozenset(
    {"s", "es", "ed", "d", "ing", "er", "est"}
)


def lemmatize_word(word: str) -> str:
    """Reduce an inflected word to its lemma (base form).

    Uses lemminflect (VERB + NOUN only — ADJ/ADV produces false positives).
    Only accepts a lemma if removing a valid inflectional suffix:
      straying → stray, eruptions → eruption, caterpillars → caterpillar
    Base forms and derivational words are left unchanged:
      linger → linger, precious → precious, peaceful → peaceful

    Returns the lemma, or the original word if no change.
    """
    import lemminflect

    w = word.strip().lower()
    # VERB first (covers -ing, -ed, -s, -es), then NOUN (plurals)
    for pos in ("VERB", "NOUN"):
        lemmas = lemminflect.getLemma(w, pos)
        if lemmas:
            lemma = lemmas[0].lower()
            if lemma == w:
                continue  # same word — try next POS
            # Sanity check: the removed suffix must be a real inflection
            suffix = w[len(lemma):]
            if suffix in _VALID_INFLECTIONS:
                return lemma
    return w


# ---------------------------------------------------------------------------
# Edge TTS (Microsoft Edge free TTS — works in China)
# ---------------------------------------------------------------------------


def _build_ssml(text: str, ipa: str | None = None, voice: str = "en-US-JennyNeural") -> str:
    """Build SSML string. If IPA is provided, use <phoneme> for precise pronunciation."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if ipa:
        # Clean IPA for SSML: strip leading/trailing slashes, normalize
        ipa_clean = ipa.strip("/")
        return (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"'
            ' xml:lang="en-US">'
            f'<voice name="{voice}">'
            f'<phoneme alphabet="ipa" ph="{ipa_clean}">{escaped}</phoneme>'
            f'</voice>'
            f'</speak>'
        )
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

    If IPA is provided, uses SSML <phoneme> tag for accurate pronunciation.
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

    If IPA is provided, uses SSML <phoneme> tag for accurate pronunciation.
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

def print_progress_bar(i: int, total: int, label: str = "", width: int = 0):
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
