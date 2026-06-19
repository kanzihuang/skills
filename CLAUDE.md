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
- **Python**: mechanical work — lemmatizes words, fetches IPA/audio from Free Dictionary API (Edge TTS + SSML fallback), generates sentence TTS via Edge TTS, packages into `.apkg` or syncs to Anki via AnkiConnect

**Scripts:**
| Script | Purpose |
|--------|---------|
| `utils.py` | Shared utilities: safe_filename, fetch_word_data, lemmatize_word, edge_tts_bytes/file, constants |
| `generate_apkg.py` | Generate standalone `.apkg` file with embedded audio |
| `sync_anki.py` | Incremental sync to Anki via AnkiConnect (only adds new words, preserves learning progress, per-word timeout with `--word-timeout`, auto-creates suspended meta manifest card for excluded words) |
| `ankiconnect.py` | AnkiConnect JSON-RPC client library |
| `coca_lookup.py` | COCA 20000 frequency check — direct set lookup + lemminflect/suffix-stripping fallback for derivational normalization (`indulgently`→`indulgent`) |
| `coca_20000.txt` | COCA 20000 lemma list (17,640 entries) |

**Dependencies:** `weread-skills` (for highlight data via WeRead API), Python packages: `genanki`, `edge-tts`, `requests`, `lemminflect`

**Design principles:**
- **Separation of concerns**: knowledge work (Claude) vs mechanical work (Python)
- **Filter-first**: all mechanical filtering (Anki dedup, COCA frequency check) happens BEFORE Claude generates content, avoiding wasted effort
- **Anki-before-COCA**: Anki dedup runs before COCA frequency check. Words already in Anki are preserved regardless of COCA frequency changes; COCA only filters truly new words
- **Lemma-first dedup**: lemmatizes all highlighted words BEFORE dedup and filtering, so inflected forms (`pondered`, `bewildered`) collapse to their lemma at the pipeline entry point. Card word, WordId, and API lookup all use lemma. Only inflectional (-ing/-ed/-s), not derivational (peaceful untouched)
- **Two-layer lemmatization**: Step 1d `lemmatize_word()` handles inflectional only (for dedup — same word, different forms). Step 1f `in_coca()` fallback (lemminflect + suffix stripping) handles derivational normalization (for frequency lookup — `indulgently`→`indulgent`, `resentfulness`→`resentful`). The two layers serve different purposes and are complementary, not redundant. Without the COCA derivational layer, words like `indulgently` (COCA has `indulgent` but not the -ly form) would be incorrectly excluded
- **bookId bridging**: `WordId = {lemma}_{bookId}` enables precise Anki ↔ WeRead matching without relying on book titles (which may differ between Chinese/English)
- **Single confirmation**: only one user prompt at the end (before sync/export); intermediate steps report progress without asking
- **Cross-book independence**: same word from different books coexists as independent cards via WordId
- **IPA-priority audio**: Claude always provides IPA → SSML `<phoneme>` synthesis (instant, no network); Free Dictionary API is script-side fallback only
- **Graceful degradation**: audio failures don't block card generation
- **Incremental safety**: sync mode only adds, never modifies existing cards
- **Meta manifest card**: one suspended card per book (`WordId = __META__{bookId}`) stores cumulative COCA-excluded words; read on subsequent syncs to skip known excluded words instantly
- **No WebFetch for well-known books**: Claude recalls real sentences from training data for well-known books (The Little Prince, Harry Potter, etc.); WebFetch/WebSearch is only for unfamiliar books
- **Per-word timeout**: each word has a 30s timeout (`--word-timeout` flag); on timeout the word is skipped and sync continues; 3 consecutive timeouts abort the sync with a summary of failed words
- **Text progress output**: plain text progress `i/N label` (in-place `\r` on real TTY, line-by-line when piped/captured; no `-v` needed); no graphical bar characters since Claude Code can't render `\r`; verbose mode adds audio source details and byte counts; media upload progress shown in same format
- **Background execution for large syncs**: when word count ≥30, run sync in background (`run_in_background: true`) with `python -u` (unbuffered) to avoid blocking the conversation for several minutes; read the output file after completion to show results
- **Auto deck naming**: deck name auto-derived as `{book_title} ({book_author})`
- **Three-stage filter pipeline**: Step 1d lemmatize → Step 1e Anki dedup → Step 1f COCA check. Anki result feeds COCA; COCA only runs on words not already in deck
- **Write tool for JSON**: Step 3 JSON output uses `Write` tool (not Bash heredoc) — skips shell buffering overhead; precede with `Bash touch` to create the file when it doesn't exist

## Integration

This repo's skills integrate with the `weread-skills` skill (installed from `Tencent/WeChatReading`) for WeRead API access. Skills reuse the same gateway URL, auth header (`Authorization: Bearer $WEREAD_API_KEY`), and flat JSON parameter conventions.

## License

Apache License 2.0 — all contributions are under this license.
