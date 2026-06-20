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
- **Claude**: knowledge work — extracts sentences from web-sourced book text (Step 3.0), provides Chinese definitions, translations, and IPA
- **Python**: mechanical work — lemmatizes words, generates word/sentence TTS via Edge TTS, syncs to Anki via AnkiConnect

**Scripts:**
| Script | Purpose |
|--------|---------|
| `utils.py` | Shared utilities: lemmatize_word, edge_tts_bytes/file, safe_filename, constants |
| `sync_anki.py` | Incremental sync to Anki via AnkiConnect (only adds new words, preserves learning progress, per-word timeout with `--word-timeout`, auto-creates suspended meta manifest card for excluded words) |
| `ankiconnect.py` | AnkiConnect JSON-RPC client library |
| `filter_pipeline.py` | Combined filter pipeline (Step 1d+1e+1f merged): clean punctuation/case → lemmatize → Anki dedup → COCA check in a single Python invocation. Strips sentence-boundary punctuation (`vexed.`→`vexed`) and normalizes case (`Clad`→`clad`) before processing — eliminates Claude round-trip data transfer, ~0.5s vs previous ~33s |
| `coca_lookup.py` | COCA 20000 frequency check — direct set lookup + lemminflect/suffix-stripping fallback for derivational normalization (`indulgently`→`indulgent`). Lemminflect only accepted when lemma is strictly shorter than input (avoids false positives like `abode` n.→`abide` v.) |
| `coca_20000.txt` | COCA 20000 lemma list (17,640 entries) |

**Dependencies:** `weread-skills` (for highlight data via WeRead API), Python packages: `edge-tts`, `lemminflect`

**Design principles:**
- **Separation of concerns**: knowledge work (Claude) vs mechanical work (Python)
- **Filter-first**: all mechanical filtering (Anki dedup, COCA frequency check) happens BEFORE Claude generates content, avoiding wasted effort
- **Anki-before-COCA**: Anki dedup runs before COCA frequency check. Words already in Anki are preserved regardless of COCA frequency changes; COCA only filters truly new words
- **Lemma-first dedup**: strips sentence-boundary punctuation and normalizes case (`vexed.`→`vexed`, `Clad`→`clad`) BEFORE lemmatization and dedup. Then lemmatizes all highlighted words so inflected forms (`pondered`) collapse to their lemma at the pipeline entry point. Card word, WordId, and API lookup all use lemma. Only inflectional (-ing/-ed/-s), not derivational (peaceful untouched)
- **Two-layer lemmatization**: Step 1d `lemmatize_word()` handles inflectional only (for dedup — same word, different forms). Step 1f `in_coca()` fallback (lemminflect + suffix stripping) handles derivational normalization (for frequency lookup — `indulgently`→`indulgent`, `resentfulness`→`resentful`). The two layers serve different purposes and are complementary, not redundant. Without the COCA derivational layer, words like `indulgently` (COCA has `indulgent` but not the -ly form) would be incorrectly excluded. Both layers use `len(lemma) < len(word)` to avoid cross-POS false positives (e.g. `abode` n.≠`abide` v.). This unified guard correctly handles doubled-consonant patterns lemminflect misses (`crammed`→`cram`, `forsaken`→`forsake`) while rejecting same-length mismatches. Same-length irregular verbs (`ran`→`run`, `sat`→`sit`) are a known limitation but rarely highlighted as new vocab
- **bookId bridging**: `WordId = {lemma}_{bookId}` (or `__META__{bookId}` for meta manifest) enables precise Anki ↔ WeRead matching without relying on book titles (which may differ between Chinese/English). Meta manifest cards (tagged `meta` + `weread`; find via `tag:meta` search to avoid deck-name quoting pitfalls) serve as authoritative bookId source in Step 0b
- **Single confirmation**: only one user prompt at the end (before sync); intermediate steps report progress without asking
- **Cross-book independence**: same word from different books coexists as independent cards via WordId
- **IPA display-only audio**: Claude provides IPA for card display; word audio uses Edge TTS default pronunciation (SSML `<phoneme>` not supported — `edge_tts.Communicate` internally `escape()`s input then wraps in its own `<speak>` via `mkssml()`, causing external SSML to be double-escaped and read as literal text including the `xmlns` URL). IPA missing → skip word audio gracefully
- **Graceful degradation**: audio failures don't block card generation
- **Incremental safety**: sync mode only adds, never modifies existing cards
- **Meta manifest card**: one suspended card per book (`WordId = __META__{bookId}`) stores cumulative COCA-excluded words; read on subsequent syncs to skip known excluded words instantly
- **Source text retrieval (Step 3.0)**: sentences are extracted from web-sourced book text via mechanical word matching — no longer rely on Claude recall. Eliminates fabricated sentences (e.g., attributing a word to the wrong passage). Falls back to recall mode only when source text is unavailable, with explicit disclaimer in Step 4 summary
- **Per-word timeout**: each word has a 30s timeout (`--word-timeout` flag); on timeout the word is skipped and sync continues; 3 consecutive timeouts abort the sync with a summary of failed words
- **Text progress output**: plain text progress `i/N label` (in-place `\r` on real TTY, line-by-line when piped/captured; no `-v` needed); no graphical bar characters since Claude Code can't render `\r`; verbose mode adds audio source details and byte counts; media upload progress shown in same format
- **Background execution for large syncs**: when word count ≥30, run sync in background (`run_in_background: true`) with `python -u` (unbuffered) to avoid blocking the conversation for several minutes; read the output file after completion to show results
- **Auto deck naming**: deck name auto-derived as `{book_title} ({book_author})`
- **Single-pass filter pipeline**: Step 1 runs `filter_pipeline.py` — one Python invocation that pipelines lemmatize → Anki dedup → COCA check. All data flows through stdin/stdout between processes; Claude never carries tab-separated word lists in echo commands. Eliminates the prior ~33s Claude round-trip overhead (capture output → regenerate as echo → re-parse) down to ~0.5s
- **JSON output via Python json.dump**: Step 3 JSON output prefers Python `json.dump` over `Write` tool — avoids Unicode quote normalization issues (Write tool may normalize Chinese curly quotes `""` to ASCII `"`, breaking JSON). Python `json.dump` with `ensure_ascii=False` preserves Chinese text correctly. Fallback to Write tool only when translations contain no special Unicode quotes
- **Batched content generation**: for >20 words, write JSON in batches of ~15-20 words using Python json.dump (preferred) or `Edit` to append to the `words` array. First batch: full JSON skeleton + first batch. Subsequent batches: `Read limit=5` → `Edit` appends new words before `  ],\n  "excluded"`. **Critical**: after pipeline output, first run Step 3.0 to fetch source text and mechanically extract all sentences. Then write JSON with pre-extracted sentences — no recall needed. Batch writing focuses on IPA + definitions + translations only; per-batch ~5-8s, total ~15-30s

## Integration

This repo's skills integrate with the `weread-skills` skill (installed from `Tencent/WeChatReading`) for WeRead API access. Skills reuse the same gateway URL, auth header (`Authorization: Bearer $WEREAD_API_KEY`), and flat JSON parameter conventions.

## License

Apache License 2.0 — all contributions are under this license.
