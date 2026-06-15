# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a skills repository for Claude Code. Skills are reusable workflow bundles that extend Claude Code's capabilities.

## Skills

### vocab-anki (`vocab-anki/`)

Generate Anki vocabulary flashcard decks from WeRead (微信读书) English book highlights.

**Architecture:** Claude ↔ Python two-phase design:
- **Claude**: knowledge work — recalls real book sentences for each highlighted word, provides Chinese definitions and translations
- **Python**: mechanical work — fetches IPA/audio from Free Dictionary API (gTTS fallback), generates sentence TTS, packages into `.apkg` or syncs to Anki via AnkiConnect

**Scripts:**
| Script | Purpose |
|--------|---------|
| `generate_apkg.py` | Generate standalone `.apkg` file with embedded audio |
| `sync_anki.py` | Incremental sync to Anki via AnkiConnect (only adds new words, preserves learning progress) |
| `ankiconnect.py` | AnkiConnect JSON-RPC client library |

**Dependencies:** `weread-skills` (for highlight data via WeRead API), Python packages: `genanki`, `gtts`, `requests`

**Design principles:**
- **Separation of concerns**: knowledge work (Claude) vs mechanical work (Python)
- **Cross-book independence**: `WordId = {word}_{bookId}` as first model field, allowing same word from different books to coexist as independent cards. Card display still uses `{{Word}}`, WordId is invisible to user
- **Graceful degradation**: audio failures don't block card generation（Free Dictionary API → gTTS fallback）
- **Incremental safety**: sync mode only adds, never modifies existing cards. Deck-only dedup via WordId field
- **Auto deck naming**: deck name auto-derived as `{book_title} ({book_author})` matching `generate_apkg.py` convention

## Integration

This repo's skills integrate with the `weread-skills` skill (installed from `Tencent/WeChatReading`) for WeRead API access. Skills reuse the same gateway URL, auth header (`Authorization: Bearer $WEREAD_API_KEY`), and flat JSON parameter conventions.

## License

Apache License 2.0 — all contributions are under this license.
