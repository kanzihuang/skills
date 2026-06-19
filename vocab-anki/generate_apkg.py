#!/usr/bin/env python3
"""Generate Anki vocabulary deck (.apkg) from WeRead English book highlights.

Accepts a JSON file with word entries (word, sentence, IPAs, Chinese definitions
and translations). Fetches word pronunciation audio from Free Dictionary API
(fallback to Edge TTS), generates sentence TTS via Edge TTS, and packages
everything into an .apkg file with embedded media.

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

from utils import (
    API_DELAY,
    FREE_DICT_API,
    REQUEST_TIMEOUT,
    download_audio,
    edge_tts_file,
    fetch_word_data,
    lemmatize_word,
    safe_filename,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_ID = 1690724513  # Fixed for stable model identity across regenerations

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
        help="Skip all TTS audio generation",
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


# safe_filename(), fetch_word_data(), download_audio() imported from utils


# ---------------------------------------------------------------------------
# Edge TTS
# ---------------------------------------------------------------------------
# generate_tts() replaced by edge_tts_file from utils


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
    lemma: str | None = None,
) -> tuple[str, str]:
    """Process audio for a single word.

    If lemma is provided, it's used for API lookup and audio filenames.
    The original form is used only for display/fallback.

    Returns (ipa, word_audio_path) where word_audio_path may be empty string.
    """
    lookup = (lemma or word).lower()
    safe = safe_filename(lookup)
    ipa = input_ipa or ""
    word_audio_path = ""

    if no_fetch and no_tts:
        return ipa, word_audio_path

    # If JSON provides IPA, use SSML directly — skip API (Claude's IPA
    # may target a specific pronunciation for heteronyms).
    if ipa and not no_tts:
        dest = os.path.join(temp_dir, f"{safe}_word.mp3")
        if edge_tts_file(lookup, dest, ipa=ipa):
            word_audio_path = dest
            if verbose:
                print(f"    word audio: SSML ({ipa})")
        return ipa, word_audio_path

    # 1. Try Free Dictionary API (using lemma for better coverage)
    fetched_ipa = None
    if not no_fetch:
        fetched_ipa, audio_url, _audio_bytes = fetch_word_data(lookup)
        if fetched_ipa or audio_url:
            if not ipa and fetched_ipa:
                ipa = fetched_ipa
            if audio_url:
                dest = os.path.join(temp_dir, f"{safe}_word.mp3")
                if download_audio(audio_url, dest):
                    word_audio_path = dest
                    if verbose:
                        print(f"    word audio: API ({ipa or 'no IPA'})")
        elif verbose:
            print(f"    word audio: API returned no data")

    # 2. Fallback to Edge TTS (SSML with IPA when available, on lemma)
    if not word_audio_path and not no_tts:
        dest = os.path.join(temp_dir, f"{safe}_word.mp3")
        fallback_ipa = fetched_ipa or None
        if edge_tts_file(lookup, dest, ipa=fallback_ipa):
            word_audio_path = dest
            if verbose:
                tag = "Edge TTS+SSML" if fallback_ipa else "Edge TTS fallback"
                print(f"    word audio: {tag}")

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
    if edge_tts_file(clean, dest):
        if verbose:
            print("    sentence audio: Edge TTS OK")
        return dest
    else:
        if verbose:
            print("    sentence audio: Edge TTS FAILED")
        return ""


# ---------------------------------------------------------------------------
# genanki model & deck
# ---------------------------------------------------------------------------


def create_model() -> "genanki.Model":
    """Create the genanki Model for vocabulary cards (COCA-English styled)."""
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
                "qfmt": """<article class="card">
  <header class="card-header">
    <h1 class="word">{{Word}}</h1>
  </header>
  <section class="pronunciation-audio">
    <span class="pronunciation">{{IPA}}</span>
    {{#IPA}}<span class="audio-button replay-button soundLink">{{WordAudio}}</span>{{/IPA}}
  </section>
  <hr class="divider">
  <section class="examples-section">
    <h2 class="section-title">Sentence</h2>
    <div class="example-single">{{Sentence}}</div>
  </section>
</article>""",
                "afmt": """{{FrontSide}}
<hr class="divider">
<article class="card">
  <section class="definition-section">
    <h2 class="section-title">Definition</h2>
    <div class="definition-content">{{DefinitionCN}}</div>
  </section>
  <hr class="divider">
  <section class="examples-section">
    <h2 class="section-title">Translation</h2>
    <div class="example-single translation-text">{{TranslationCN}}</div>
    <div class="example-audio-row">{{SentenceAudio}}</div>
  </section>
</article>""",
            }
        ],
        css=COCA_CSS,
    )


# ---------------------------------------------------------------------------
# COCA-English inspired CSS (adapted for vocab-anki model)
# ---------------------------------------------------------------------------

COCA_CSS = """\
/* ===== CSS Custom Properties (Theme System) ===== */
:root {
  --fg: #1f2937;
  --fg-subtle: #6b7280;
  --canvas: #fffff;
  --canvas-elevated: #ffffff;
  --canvas-inset: #f9fafb;
  --border: #e5e7eb;
  --border-subtle: #f3f4f6;
  --border-radius: 10px;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  
  --word-color: #111827;
  --pos-bg: #dbeafe;
  --pos-color: #1e40af;
  --pronunciation-color: #374151;
  --audio-color: #4b5563;
  --audio-hover-color: #1f2937;
  --definition-color: #374151;
  --example-color: #4b5563;
  --example-highlight: #3b82f6;
  --grammar-color: #14B8A6;
  --hr-color: #9ca3af;
  
  --button-bg: #f3f4f6;
  --button-hover-bg: #e5e7eb;
  --svg-path: #6b7280;
  
  --font-family: Georgia Regular;
  --font-serif: Georgia Regular;
  
  --text-xs: 12px;
  --text-sm: 14px;
  --text-base: 16px;
  --text-lg: 18px;
  --text-xl: 20px;
  --text-2xl: 24px;
  --text-3xl: 30px;
  --text-4xl: 36px;
  --text-5xl: 48px;
  
  --word-size: var(--text-5xl);
  --pos-size: var(--text-sm);
  --pronunciation-size: var(--text-xl);
  --definition-size: var(--text-lg);
  --example-size: var(--text-base);
  --grammar-size: var(--text-base);
  
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-base: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;
  
  --audio-button-size: calc(var(--text-base) * (40 / 18));
  
  --line-height-tight: 1.25;
  --line-height-normal: 1.5;
  --line-height-relaxed: 1.625;
}

/* ===== Responsive Font Sizes ===== */
@media (min-width: 475px) {
  :root {
    --text-xs: 14px;
    --text-sm: 16px;
    --text-base: 18px;
    --text-lg: 20px;
    --text-xl: 22px;
    --text-2xl: 26px;
    --text-3xl: 32px;
    --text-4xl: 40px;
    --text-5xl: 52px;
  }
}

/* ===== Basic Style Reset ===== */
*,
::after,
::before {
  box-sizing: border-box;
  border-width: 0;
  border-style: solid;
}

html,
body {
  margin: 0;
  padding: 0;
  line-height: var(--line-height-normal);
  -webkit-text-size-adjust: 100%;
  -webkit-tap-highlight-color: transparent;
  font-family: var(--font-family);
  color: var(--fg);
}

h1, h2, h3, h4, h5, h6, p {
  margin: 0;
  font-size: inherit;
  font-weight: inherit;
  color: inherit;
}

ul, ol {
  list-style: none;
  margin: 0;
  padding: 0;
}

/* ===== Card Body Style ===== */
.card {
  position: relative;
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: var(--spacing-lg);
  background-color: var(--canvas);
  border-radius: var(--border-radius);
  color: var(--fg);
  text-align: left;
  font-size: var(--text-base);
  line-height: var(--line-height-normal);
}

/* Logo Link Styles */
.dictionary-logo-link {
  position: absolute;
  top: var(--spacing-lg);
  right: var(--spacing-lg);
  width: 50px;
  height: 50px;
  z-index: 999;
  display: block;
}

.dictionary-logo-img {
  width: 100%;
  height: 100%;
  display: block;
}

.dictionary-logo-link .logo-dark {
  display: none;
}

.dictionary-logo-link .logo-light {
  display: block;
}

/* ===== Card Header ===== */
.card-header {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-lg);
  flex-wrap: wrap;
  padding-right: calc(50px + var(--spacing-lg) + var(--spacing-sm));
}

.word {
  font-size: var(--word-size);
  font-weight: 700;
  color: var(--word-color);
  line-height: var(--line-height-tight);
  font-family: var(--font-serif);
  overflow-wrap: break-word;
  min-width: 0;
}

.pos-badge {
  background: var(--pos-bg);
  color: var(--pos-color);
  font-size: var(--text-sm);
  font-weight: 600;
  padding: var(--spacing-xs) var(--spacing-sm);
  border-radius: calc(var(--border-radius) / 2);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  line-height: 1;
  white-space: nowrap;
}

.pos-badge.is-empty {
  visibility: hidden;
}

/* ===== Grammar Information ===== */
.grammar {
  color: var(--grammar-color);
  font-size: var(--grammar-size);
  font-style: italic;
  margin-bottom: var(--spacing-base);
  line-height: var(--line-height-normal);
}

/* ===== Pronunciation and Audio ===== */
.pronunciation-audio {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-base);
}

.pronunciation {
  font-size: var(--pronunciation-size);
  color: var(--pronunciation-color);
  font-style: italic;
  font-family: var(--font-serif);
}

.audio-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--audio-button-size);
  height: var(--audio-button-size);
  cursor: pointer;
  border-radius: 50% !important;
}

.audio-button svg {
  width: 80%;
  height: 80%;
}

.audio-button svg path {
  fill: var(--svg-path);
  transition: fill 0.2s ease;
}

.audio-button:hover svg path {
  fill: var(--audio-hover-color);
}

.tts-button {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--audio-button-size);
  height: var(--audio-button-size);
  border-radius: 50% !important;
  text-decoration: none;
  color: inherit;
  margin: 0;
}

/* ===== Separator Line ===== */
.divider {
  margin: var(--spacing-lg) 0;
  border: none;
  border-top: 1px solid var(--hr-color);
}

/* ===== Definition Section ===== */
.definition-section {
  margin-bottom: var(--spacing-lg);
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--fg);
  margin-bottom: var(--spacing-sm);
}

.definition-content {
  font-size: var(--definition-size);
  color: var(--definition-color);
  line-height: var(--line-height-relaxed);
}

/* ===== Example Sentences Section ===== */
.examples-section {
  margin-bottom: var(--spacing-lg);
}

.examples-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.example-sentence {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
  min-width: 0;
}

.example-sentence:last-child {
  margin-bottom: 0;
}

.example-item {
  font-size: var(--example-size);
  color: var(--example-color);
  line-height: var(--line-height-relaxed);
  padding-left: var(--spacing-base);
  position: relative;
  flex: 1;
  min-width: 0;
}

/* Support for front side simple list structure */
.examples-list > .example-item {
  margin-bottom: var(--spacing-sm);
}

.examples-list > .example-item:last-child {
  margin-bottom: 0;
}

.example-item::before {
  content: '•';
  color: var(--example-highlight);
  font-weight: bold;
  position: absolute;
  left: 0;
}

.example-item em {
  color: var(--example-highlight);
  font-style: italic;
  font-weight: 500;
}

.example-audio {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  flex-shrink: 0;
  gap: 0.2em;
}

/* ===== Mobile Optimization ===== */
@media (max-width: 475px) {
  .card {
    padding: var(--spacing-base);
    margin: var(--spacing-xs);
  }
  
  .word {
    font-size: var(--text-4xl);
  }
  
  .pronunciation {
    font-size: var(--text-lg);
  }
  
  .audio-button {
    border-radius: 50% !important;
  }
}

/* ===== Large Screen Optimization ===== */
@media (min-width: 1024px) {
  :root {
    --text-xs: 16px;
    --text-sm: 18px;
    --text-base: 20px;
    --text-lg: 24px;
    --text-xl: 26px;
    --text-2xl: 32px;
    --text-3xl: 38px;
    --text-4xl: 46px;
    --text-5xl: 58px;
    
    --spacing-base: 20px;
    --spacing-lg: 28px;
    --spacing-xl: 36px;
  }
  
  .card {
    max-width: 1024px;
  }
}

@media (min-width: 475px) {
  .example-audio {
    flex-direction: row;
  }
}

/* ===== Mobile Border Handling ===== */
.ios .card,
.android .card {
  border-radius: 0;
  margin: 0;
}

.ios *,
.android * {
  border-left-width: 0;
  border-right-width: 0;
  border-radius: 0;
}

/* ===== iOS Specific Styles ===== */
.ios .card {
  padding-bottom: calc(var(--spacing-lg) + env(safe-area-inset-bottom));
}

/* ===== AnkiWeb Style Adaptation ===== */
#quiz {
  --canvas: #fff;
}

#quiz #qa {
  margin-top: 0;
}

#quiz .card {
  padding: var(--spacing-base);
  margin: 0;
  max-width: none;
  box-shadow: none;
  border-radius: 0;
}

/* ===== Hidden Class ===== */
.hidden {
  display: none !important;
}

/* ===== Text Alignment ===== */
.text-center {
  text-align: center;
}

/* ===== Accessibility (Reduced Motion) ===== */
@media (prefers-reduced-motion: reduce) {
  .audio-button svg path {
    transition: none;
  }
}

/* ===== Print Styles ===== */
@media print {
  .audio-button {
    display: none;
  }
}

/* ===== Dark Mode CSS Variables ===== */
:root.night-mode,
:root .night_mode,
:root .nightMode,
[data-bs-theme='dark'] {
  --fg: #e5e7eb;
  --fg-subtle: #d1d5db;
  --canvas: #2c2c2c;
  --canvas-elevated: #363636;
  --canvas-inset: #2c2c2c;
  --border: #494949;
  --border-subtle: #4b5563;
  
  --word-color: #f9fafb;
  --pos-bg: #1e40af;
  --pos-color: #dbeafe;
  --pronunciation-color: #e5e7eb;
  --audio-color: #d1d5db;
  --audio-hover-color: #f3f4f6;
  --definition-color: #e5e7eb;
  --example-color: #d1d5db;
  --example-highlight: #60a5fa;
  --grammar-color: #34d399;
  --hr-color: #374151;
  
  --button-bg: #404040;
  --button-hover-bg: #4b5563;
  --svg-path: #d1d5db;
}

/* Dark mode for logo link */
:root.night-mode .dictionary-logo-link .logo-light,
:root .night_mode .dictionary-logo-link .logo-light,
:root .nightMode .dictionary-logo-link .logo-light,
[data-bs-theme='dark'] .dictionary-logo-link .logo-light {
  display: none;
}

:root.night-mode .dictionary-logo-link .logo-dark,
:root .night_mode .dictionary-logo-link .logo-dark,
:root .nightMode .dictionary-logo-link .logo-dark,
[data-bs-theme='dark'] .dictionary-logo-link .logo-dark {
  display: block;
}
/* ===== vocab-anki specific ===== */
.example-single b, .example-single strong, .example-single em {
  color: var(--example-highlight);
  font-style: italic;
  font-weight: 600;
}
.translation-text { margin-bottom: var(--spacing-sm); }
.example-audio-row {
  display: flex; align-items: center; gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);
}

/* ===== vocab-anki spacing ===== */
.card {
  padding-top: var(--spacing-sm);
  padding-bottom: var(--spacing-sm);
}
.divider { margin: var(--spacing-sm) 0; }
.definition-section { margin-bottom: 0; }
.examples-section { margin-bottom: 0; }
.definition-section .section-title { margin-bottom: var(--spacing-xs); }
.examples-section .section-title { margin-bottom: var(--spacing-xs); }
.example-single b, .example-single strong, .example-single em {
  color: var(--example-highlight);
  font-style: italic;
  font-weight: 600;
}
.translation-text { margin-bottom: var(--spacing-sm); }
.example-audio-row {
  display: flex; align-items: center; gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);
}
.card-header { margin-bottom: var(--spacing-sm); }
.pronunciation-audio { margin-bottom: 0; }
"""


# ---------------------------------------------------------------------------
# Package generation
# ---------------------------------------------------------------------------


def generate_package(
    data: dict,
    audio_results: list[dict],
    output_path: str,
) -> None:
    """Create and write the genanki .apkg package.
/* ===== vocab-anki spacing ===== */
.card {
  padding-top: var(--spacing-sm);
  padding-bottom: var(--spacing-sm);
}
.divider { margin: var(--spacing-sm) 0; }
.definition-section { margin-bottom: 0; }
.examples-section { margin-bottom: 0; }
.definition-section .section-title { margin-bottom: var(--spacing-xs); }
.examples-section .section-title { margin-bottom: var(--spacing-xs); }
.example-single b, .example-single strong, .example-single em {
  color: var(--example-highlight);
  font-style: italic;
  font-weight: 600;
}
.translation-text { margin-bottom: var(--spacing-sm); }
.example-audio-row {
  display: flex; align-items: center; gap: var(--spacing-sm);
  margin-top: var(--spacing-sm);
}
.card-header { margin-bottom: var(--spacing-sm); }
.pronunciation-audio { margin-bottom: 0; }
"""
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

    # Check edge-tts availability early
    if not args.no_tts:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            print(
                "Warning: edge-tts not installed. Use --no-tts to skip audio generation.\n"
                "  pip install edge-tts",
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
            lemma = lemmatize_word(word)
            display = lemma if lemma != word.lower() else word
            input_ipa = entry.get("ipa", "")

            if args.verbose:
                tag = f" ({lemma})" if lemma != word.lower() else ""
                print(f"  [{i}/{total}] {word}{tag}")

            # Process word audio (IPA fetch + audio download, using lemma)
            ipa, word_audio = process_word_audio(
                word,
                input_ipa,
                temp_dir,
                args.verbose,
                args.no_fetch_audio,
                args.no_tts,
                lemma=lemma,
            )

            # Process sentence TTS
            sent_audio = process_sentence_audio(
                entry["sentence"],
                display,
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
                label = f"{word}→{display}" if display != word else word
                print(f"  [{i}/{total}] {label} -- {status}")

            audio_results.append(
                {
                    "word": display,
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
