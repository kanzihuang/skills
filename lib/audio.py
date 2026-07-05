"""Audio utilities: media upload and repair.

Provides direct filesystem copy into Anki's collection.media (about
100x faster than AnkiConnect storeMediaFile) and per-card audio repair.
"""

from __future__ import annotations

import glob
import os
import platform
import re

from .ankiconnect import AnkiConnect
from .utils import edge_tts_bytes, print_progress, safe_filename


def _find_anki_media_dir() -> str | None:
    """Locate Anki's collection.media directory on the local filesystem.

    Probes common OS paths (including WSL2 -> Windows host). Returns the
    first writable collection.media directory found, or None.
    """
    candidates: list[str] = []
    home = os.path.expanduser("~")

    if platform.system() == "Windows":
        candidates.append(os.path.join(os.getenv("APPDATA", ""), "Anki2"))
    else:
        candidates.append(os.path.join(home, ".local", "share", "Anki2"))
        candidates.append(
            os.path.join(home, ".var", "app", "net.ankiweb.Anki", "data", "Anki2")
        )
        candidates.append(
            os.path.join(home, "Library", "Application Support", "Anki2")
        )
        wsl_users = glob.glob("/mnt/c/Users/*/AppData/Roaming/Anki2")
        candidates.extend(wsl_users)

    for base in candidates:
        if not os.path.isdir(base):
            continue
        for profile in os.listdir(base):
            media_dir = os.path.join(base, profile, "collection.media")
            if os.path.isdir(media_dir) and os.access(media_dir, os.W_OK):
                return media_dir
    return None


def _upload_media_direct(
    audio_uploads: list[tuple[str, bytes]], media_dir: str, verbose: bool = False
) -> int:
    """Copy audio files directly into Anki's collection.media directory.

    Much faster than AnkiConnect storeMediaFile (~0.7s for 124 files vs
    ~80s through the API).
    """
    total = len(audio_uploads)
    copied = 0
    for i, (filename, data) in enumerate(audio_uploads, 1):
        dest = os.path.join(media_dir, filename)
        try:
            with open(dest, "wb") as f:
                f.write(data)
            copied += 1
            if verbose:
                print_progress(i, total, f"{filename} ({len(data)} bytes)")
            else:
                print_progress(i, total)
        except OSError:
            print()
            print(f"  x {filename}: write failed")
            print_progress(i, total)
    return copied


def _repair_audio(
    ac: AnkiConnect, lemma: str, sentence: str, book_id: str
) -> None:
    """Re-upload word + sentence audio for a repaired card."""
    safe = safe_filename(lemma)
    # Word audio
    word_tts = edge_tts_bytes(lemma)
    if word_tts:
        ac.store_media_file(f"{safe}_{book_id}_word.mp3", word_tts)
    # Sentence audio
    if sentence:
        clean = re.sub(r"<[^>]+>", "", sentence)
        sent_tts = edge_tts_bytes(clean)
        if sent_tts:
            ac.store_media_file(f"{safe}_{book_id}_sent.mp3", sent_tts)
