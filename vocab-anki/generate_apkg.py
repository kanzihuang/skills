#!/usr/bin/env python3
"""Generate Anki vocabulary deck (.apkg) from WeRead English book highlights.

Accepts a JSON file with word entries (word, sentence, IPAs, Chinese definitions
and translations). Fetches word pronunciation audio from Free Dictionary API
(fallback to gTTS), generates sentence TTS via gTTS, and packages everything
into an .apkg file with embedded media.

Usage:
    python generate_apkg.py input.json -o output.apkg
    python generate_apkg.py input.json -o output.apkg --no-fetch-audio --no-tts
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_ID = 1690724513  # Fixed for stable model identity across regenerations
FREE_DICT_API = "https://api.dictionaryapi.dev/api/v2/entries/en"
API_DELAY = 0.35  # seconds between Free Dictionary API requests
REQUEST_TIMEOUT = 12
MAX_RETRIES = 1

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Anki vocabulary deck (.apkg) from word entries"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=None,
        help="JSON input file (default: read from stdin)",
    )
    parser.add_argument(
        "-o", "--output", required=True, help="Output .apkg file path"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed progress"
    )
    parser.add_argument(
        "--no-fetch-audio",
        action="store_true",
        help="Skip Free Dictionary API audio fetching",
    )
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="Skip all gTTS audio generation",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def validate_input(data: dict) -> list[str]:
    """Validate the JSON input structure. Returns a list of error messages."""
    errors = []
    if "book_title" not in data:
        errors.append("Missing required field: book_title")
    if "book_id" not in data:
        errors.append("Missing required field: book_id")
    if "words" not in data:
        errors.append("Missing required field: words")
    elif not isinstance(data["words"], list):
        errors.append("'words' must be an array")
    elif len(data["words"]) == 0:
        errors.append("'words' array is empty")
    else:
        required_fields = ["word", "sentence", "definition_cn", "translation_cn"]
        for i, w in enumerate(data["words"]):
            for field in required_fields:
                if field not in w or not w[field]:
                    errors.append(f"words[{i}]: missing or empty '{field}'")
    return errors


def deduplicate_words(words: list[dict]) -> list[dict]:
    """Remove duplicate words (case-insensitive), first occurrence wins."""
    seen = set()
    result = []
    for w in words:
        key = w["word"].strip().lower()
        if key not in seen:
            seen.add(key)
            result.append(w)
    return result


# ---------------------------------------------------------------------------
# Filename utilities
# ---------------------------------------------------------------------------


def safe_filename(word: str) -> str:
    """Sanitize a word to a safe filesystem name (alphanumeric + underscore)."""
    safe = re.sub(r"[^a-zA-Z0-9]", "_", word)
    return safe.strip("_").lower() or "word"


# ---------------------------------------------------------------------------
# Free Dictionary API
# ---------------------------------------------------------------------------


def fetch_word_data(word: str) -> dict | None:
    """Fetch word data from Free Dictionary API.

    Returns dict with 'ipa' and 'audio_url' keys, or None if not found.
    """
    url = f"{FREE_DICT_API}/{word.lower()}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, list) or len(data) == 0:
            return None

        entry = data[0]

        # Extract IPA: try root phonetic first, then phonetics array
        ipa = entry.get("phonetic")
        if not ipa:
            for p in entry.get("phonetics", []):
                if p.get("text"):
                    ipa = p["text"]
                    break

        # Extract audio: prefer US, fallback to any
        audio_url = None
        phonetics = entry.get("phonetics", [])
        # Try US first
        for p in phonetics:
            if p.get("audio") and (
                "us" in p.get("audio", "").lower()
                or "-us" in str(p.get("text", "")).lower()
            ):
                audio_url = p["audio"]
                break
        # Fallback to any
        if not audio_url:
            for p in phonetics:
                if p.get("audio"):
                    audio_url = p["audio"]
                    break

        return {
            "ipa": ipa,
            "audio_url": audio_url,
        }
    except requests.RequestException:
        return None


def download_audio(url: str, dest_path: str, retries: int = MAX_RETRIES) -> bool:
    """Download an audio file from URL to dest_path. Returns True on success."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
                return True
        except requests.RequestException:
            if attempt < retries:
                time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# gTTS
# ---------------------------------------------------------------------------


def generate_tts(text: str, dest_path: str, lang: str = "en") -> bool:
    """Generate TTS audio for text using gTTS. Returns True on success."""
    try:
        from gtts import gTTS

        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(dest_path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Audio pipeline
# ---------------------------------------------------------------------------


def process_word_audio(
    word: str,
    input_ipa: str | None,
    temp_dir: str,
    verbose: bool,
    no_fetch: bool,
    no_tts: bool,
) -> tuple[str, str]:
    """Process audio for a single word.

    Returns (ipa, word_audio_path) where word_audio_path may be empty string.
    """
    safe = safe_filename(word)
    ipa = input_ipa or ""
    word_audio_path = ""

    if no_fetch and no_tts:
        return ipa, word_audio_path

    # 1. Try Free Dictionary API
    api_data = None
    if not no_fetch:
        api_data = fetch_word_data(word)
        if api_data:
            if not ipa and api_data.get("ipa"):
                ipa = api_data["ipa"]
            if api_data.get("audio_url"):
                dest = os.path.join(temp_dir, f"{safe}_word.mp3")
                if download_audio(api_data["audio_url"], dest):
                    word_audio_path = dest
                    if verbose:
                        print(f"    word audio: API ({ipa or 'no IPA'})")
        elif verbose:
            print(f"    word audio: API returned no data")

    # 2. Fallback to gTTS
    if not word_audio_path and not no_tts:
        dest = os.path.join(temp_dir, f"{safe}_word.mp3")
        if generate_tts(word, dest):
            word_audio_path = dest
            if verbose:
                print("    word audio: gTTS fallback")

    return ipa, word_audio_path


def process_sentence_audio(
    sentence: str,
    word_key: str,
    temp_dir: str,
    verbose: bool,
    no_tts: bool,
) -> str:
    """Generate TTS for the sentence. Returns audio file path or empty string."""
    if no_tts:
        return ""

    safe = safe_filename(word_key)
    dest = os.path.join(temp_dir, f"{safe}_sent.mp3")

    # Strip HTML tags for clean TTS
    clean = re.sub(r"<[^>]+>", "", sentence)
    if generate_tts(clean, dest):
        if verbose:
            print("    sentence audio: gTTS OK")
        return dest
    else:
        if verbose:
            print("    sentence audio: gTTS FAILED")
        return ""


# ---------------------------------------------------------------------------
# genanki model & deck
# ---------------------------------------------------------------------------


def create_model() -> "genanki.Model":
    """Create the genanki Model for vocabulary cards."""
    import genanki

    return genanki.Model(
        MODEL_ID,
        "Vocabulary Card (WeRead)",
        fields=[
            {"name": "WordId"},
            {"name": "Word"},
            {"name": "Sentence"},
            {"name": "IPA"},
            {"name": "DefinitionCN"},
            {"name": "TranslationCN"},
            {"name": "WordAudio"},
            {"name": "SentenceAudio"},
        ],
        templates=[
            {
                "name": "Vocabulary Card",
                "qfmt": """<div class="card">
  <div class="word">{{Word}}</div>
  <hr>
  <div class="sentence">{{Sentence}}</div>
</div>""",
                "afmt": """{{FrontSide}}
<hr id="answer">
<div class="card back">
  <div class="section">
    <div class="label">IPA</div>
    <div class="ipa">{{IPA}}</div>
  </div>
  <div class="section">
    <div class="label">释义</div>
    <div class="definition">{{DefinitionCN}}</div>
  </div>
  <div class="section">
    <div class="label">例句翻译</div>
    <div class="translation">{{TranslationCN}}</div>
  </div>
  <div class="audio-row">{{WordAudio}} {{SentenceAudio}}</div>
</div>""",
            }
        ],
        css="""/* Base */
.card {
  font-family: "Helvetica Neue", "PingFang SC", "Noto Sans SC", Arial, sans-serif;
  font-size: 20px;
  text-align: center;
  color: #333;
  padding: 20px;
}

/* Front */
.word {
  font-size: 40px;
  font-weight: 700;
  color: #1a1a1a;
  margin-bottom: 20px;
}

.sentence {
  font-size: 22px;
  line-height: 1.6;
  color: #444;
  padding: 0 12px;
}

.sentence b, .sentence strong {
  color: #2563eb;
  font-weight: 700;
}

/* Back */
.back { text-align: center; }

.section {
  margin: 14px 0;
}

.label {
  font-size: 13px;
  color: #999;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.ipa {
  font-size: 22px;
  color: #555;
  font-style: italic;
}

.definition {
  font-size: 22px;
  color: #1e40af;
  font-weight: 600;
}

.translation {
  font-size: 20px;
  color: #666;
  line-height: 1.5;
}

.audio-row {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  gap: 12px;
}

/* Override Anki's default play button styling for Chinese labels */
.replay-button {
  display: inline-block;
}

/* Night mode */
.night_mode .card { color: #e5e7eb; }
.night_mode .word { color: #f0f0f0; }
.night_mode .sentence { color: #d1d5db; }
.night_mode .sentence b, .night_mode .sentence strong { color: #60a5fa; }
.night_mode .label { color: #9ca3af; }
.night_mode .ipa { color: #d1d5db; }
.night_mode .definition { color: #93c5fd; }
.night_mode .translation { color: #a8a29e; }
""",
    )


# ---------------------------------------------------------------------------
# Package generation
# ---------------------------------------------------------------------------


def generate_package(
    data: dict,
    audio_results: list[dict],
    output_path: str,
) -> None:
    """Create and write the genanki .apkg package."""
    import genanki

    model = create_model()

    # Deterministic deck ID from book title
    deck_id = int(
        hashlib.md5(data["book_title"].encode()).hexdigest()[:8], 16
    )
    deck_name = f"{data['book_title']} Vocabulary"
    if data.get("book_author"):
        deck_name = f"{data['book_title']} ({data['book_author']})"

    deck = genanki.Deck(deck_id, deck_name)

    media_files = []

    for entry in audio_results:
        safe = safe_filename(entry["word"])
        word_audio = entry.get("word_audio", "")
        sent_audio = entry.get("sent_audio", "")

        # Collect media paths
        for path in (word_audio, sent_audio):
            if path and os.path.isfile(path):
                media_files.append(path)

        # Build [sound:] references
        word_sound = f"[sound:{safe}_word.mp3]" if word_audio else ""
        sent_sound = f"[sound:{safe}_sent.mp3]" if sent_audio else ""

        word_id = f"{entry['word'].strip().lower()}_{data['book_id']}"

        note = genanki.Note(
            model=model,
            fields=[
                word_id,
                entry["word"],
                entry["sentence"],
                entry.get("ipa", ""),
                entry.get("definition_cn", ""),
                entry.get("translation_cn", ""),
                word_sound,
                sent_sound,
            ],
        )
        deck.add_note(note)

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    # Read input
    if args.input_file:
        with open(args.input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    # Validate
    errors = validate_input(data)
    if errors:
        print("Input validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # Deduplicate
    original_count = len(data["words"])
    data["words"] = deduplicate_words(data["words"])
    if len(data["words"]) < original_count:
        print(
            f"Note: deduplicated {original_count - len(data['words'])} word(s)"
        )

    total = len(data["words"])
    book_title = data["book_title"]
    print(f'Processing {total} vocabulary words for "{book_title}"...')
    print()

    # Check gTTS availability early
    if not args.no_tts:
        try:
            import gtts  # noqa: F401
        except ImportError:
            print(
                "Warning: gtts not installed. Use --no-tts to skip audio generation.\n"
                "  pip install gtts",
                file=sys.stderr,
            )

    # Ensure output directory exists
    output_dir = os.path.dirname(os.path.abspath(args.output))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    temp_dir = tempfile.mkdtemp(prefix="vocab_anki_")

    try:
        audio_results = []

        for i, entry in enumerate(data["words"], 1):
            word = entry["word"]
            input_ipa = entry.get("ipa", "")

            if args.verbose:
                print(
                    f"  [{i}/{total}] {word}"
                )

            # Process word audio (IPA fetch + audio download)
            ipa, word_audio = process_word_audio(
                word,
                input_ipa,
                temp_dir,
                args.verbose,
                args.no_fetch_audio,
                args.no_tts,
            )

            # Process sentence TTS
            sent_audio = process_sentence_audio(
                entry["sentence"],
                word,
                temp_dir,
                args.verbose,
                args.no_tts,
            )

            if not args.verbose:
                status_parts = []
                if word_audio:
                    status_parts.append("word audio OK")
                elif not args.no_tts:
                    status_parts.append("word audio MISS")
                if sent_audio:
                    status_parts.append("sent audio OK")
                elif not args.no_tts:
                    status_parts.append("sent audio MISS")
                status = ", ".join(status_parts) if status_parts else "text only"
                print(f"  [{i}/{total}] {word} -- {status}")

            audio_results.append(
                {
                    "word": word,
                    "sentence": entry["sentence"],
                    "ipa": ipa,
                    "definition_cn": entry["definition_cn"],
                    "translation_cn": entry["translation_cn"],
                    "word_audio": word_audio,
                    "sent_audio": sent_audio,
                }
            )

            # Rate limit for API
            if not args.no_fetch_audio:
                time.sleep(API_DELAY)

        # Generate package
        print()
        print(f"Writing {args.output} ...")
        generate_package(data, audio_results, args.output)

        # Summary
        word_audio_count = sum(
            1 for a in audio_results if a["word_audio"]
        )
        sent_audio_count = sum(
            1 for a in audio_results if a["sent_audio"]
        )
        print(
            f"Done! {total} cards, "
            f"{word_audio_count} word audio, "
            f"{sent_audio_count} sentence audio"
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
