#!/usr/bin/env python3
"""Shared utilities for vocab-anki scripts.

Provides constants, filename helpers, and Free Dictionary API access
used by both generate_apkg.py and sync_anki.py.
"""

import os
import re
import sys
import tempfile
import time

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FREE_DICT_API = "https://api.dictionaryapi.dev/api/v2/entries/en"
API_DELAY = 0.35  # seconds between Free Dictionary API requests
REQUEST_TIMEOUT = 12
MAX_RETRIES = 1
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
# Free Dictionary API
# ---------------------------------------------------------------------------


def fetch_word_data(word: str) -> tuple[str | None, str | None, bytes | None]:
    """Fetch word data from Free Dictionary API.

    Returns (ipa, audio_url, audio_bytes) — each can be None.
    Prefers US pronunciation (K.K. phonetics) over UK.
    """
    url = f"{FREE_DICT_API}/{word.lower()}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None, None, None
        data = resp.json()
        if not isinstance(data, list) or len(data) == 0:
            return None, None, None

        entry = data[0]

        # Extract IPA: prefer US, then root, then any
        ipa = _extract_ipa(entry)

        # Extract audio: prefer US, fallback to any
        audio_url = _extract_audio_url(entry)

        # Download audio bytes if URL is available
        audio_bytes = None
        if audio_url:
            audio_bytes = _download_audio_bytes(audio_url)

        return ipa, audio_url, audio_bytes

    except requests.RequestException:
        return None, None, None


def _extract_ipa(entry: dict) -> str | None:
    """Extract IPA from a Free Dictionary API entry, preferring US."""
    ipa = None
    phonetics = entry.get("phonetics", [])
    for p in phonetics:
        audio = p.get("audio", "")
        text = p.get("text", "")
        is_us = "us" in audio.lower() or "-us" in str(text).lower()
        if not is_us:
            # Heuristic: US IPA uses ɚ ɑ ɝ; UK uses ɒ ɪə eə
            is_us = any(c in text for c in ("ɚ", "ɑ", "ɝ"))
        if is_us and text:
            ipa = text
            break
    # Fallback: root-level phonetic
    if not ipa:
        ipa = entry.get("phonetic")
    # Fallback: first available phonetic text
    if not ipa:
        for p in phonetics:
            if p.get("text"):
                ipa = p["text"]
                break
    return ipa


def _extract_audio_url(entry: dict) -> str | None:
    """Extract audio URL from a Free Dictionary API entry, preferring US."""
    phonetics = entry.get("phonetics", [])
    # Try US first
    for p in phonetics:
        if p.get("audio") and (
            "us" in p.get("audio", "").lower()
            or "-us" in str(p.get("text", "")).lower()
        ):
            return p["audio"]
    # Fallback to any
    for p in phonetics:
        if p.get("audio"):
            return p["audio"]
    return None


def _download_audio_bytes(url: str) -> bytes | None:
    """Download audio from URL, return raw bytes or None on failure."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.content
        except requests.RequestException:
            if attempt < MAX_RETRIES:
                time.sleep(1)
    return None


def download_audio(url: str, dest_path: str) -> bool:
    """Download audio from URL to a file path. Returns True on success."""
    audio_bytes = _download_audio_bytes(url)
    if audio_bytes:
        with open(dest_path, "wb") as f:
            f.write(audio_bytes)
        return True
    return False


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
