# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a skills repository for Claude Code. Skills are reusable workflow bundles that extend Claude Code's capabilities.

## Skills

### weekly-report (`weekly-report/`)

Generate weekly work reports from daily reports. Categorizes similar tasks across days, outputs Markdown and HTML files, copies HTML to Windows clipboard, and opens the report in a browser.

**Architecture:** Claude-only workflow (no Python scripts):
- **Claude**: knowledge work — parses daily reports, categorizes items, consolidates next-week plans
- **PowerShell**: clipboard — formats HTML clipboard data with proper offsets, opens in Edge

**Scripts:**
| Script | Purpose |
|--------|---------|
| `scripts/to-clipboard.ps1` | Copy HTML to Windows clipboard in HTML format and open in Edge |

**Triggers:** "周报", "weekly report", "本周日报", or pasting multi-day daily reports

**Design principles:**
- **Format-constrained output**: strict Markdown and HTML templates ensure consistent, paste-ready reports
- **Category inference**: groups similar tasks across days into logical categories (e.g., 运维审计, 乐效CD, 域名备案)
- **Degradation awareness**: clipboard and browser steps are Windows-only; report files are always generated regardless

### vocab-anki (`vocab-anki/`)

Generate Anki vocabulary flashcard decks from WeRead (微信读书) English book highlights.

**Architecture:** Claude ↔ Python two-phase design:
- **Claude**: knowledge work — recalls real book sentences for each highlighted word, provides Chinese definitions and translations
- **Python**: mechanical work — fetches IPA/audio from Free Dictionary API (gTTS fallback), generates sentence TTS, packages into `.apkg` or syncs to Anki via AnkiConnect

**Scripts:**
| Script | Purpose |
|--------|---------|
| `utils.py` | Shared utilities: safe_filename, fetch_word_data, constants |
| `generate_apkg.py` | Generate standalone `.apkg` file with embedded audio |
| `sync_anki.py` | Incremental sync to Anki via AnkiConnect (only adds new words, preserves learning progress) |
| `ankiconnect.py` | AnkiConnect JSON-RPC client library |
| `coca_lookup.py` | COCA 20000 frequency check with CLI batch mode |
| `coca_20000.txt` | COCA 20000 lemma list (17,640 entries) |

**Dependencies:** `weread-skills` (for highlight data via WeRead API), Python packages: `genanki`, `edge-tts`, `requests`, `lemminflect`

**Design principles:**
- **Separation of concerns**: knowledge work (Claude) vs mechanical work (Python)
- **Filter-first**: COCA frequency check and Anki dedup happen BEFORE Claude generates content, avoiding wasted effort
- **bookId bridging**: `WordId = {word}_{bookId}` enables precise Anki ↔ WeRead matching without relying on book titles (which may differ between Chinese/English)
- **Single confirmation**: only one user prompt at the end (before sync/export); intermediate steps report progress without asking
- **Cross-book independence**: same word from different books coexists as independent cards via WordId
- **Graceful degradation**: audio failures don't block card generation（Free Dictionary API → Edge TTS + SSML fallback）
- **Incremental safety**: sync mode only adds, never modifies existing cards
- **Sync timeout**: 120s timeout prevents hangs; clear error messages with recovery suggestions
- **Auto deck naming**: deck name auto-derived as `{book_title} ({book_author})`

## Integration

This repo's skills integrate with the `weread-skills` skill (installed from `Tencent/WeChatReading`) for WeRead API access. Skills reuse the same gateway URL, auth header (`Authorization: Bearer $WEREAD_API_KEY`), and flat JSON parameter conventions.

## License

Apache License 2.0 — all contributions are under this license.
