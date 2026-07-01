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
| `sync_anki.py` | Incremental sync to Anki via AnkiConnect (only adds new words, preserves learning progress, per-word timeout with `--word-timeout`, triggers AnkiWeb sync after cards added unless `--no-ankiweb-sync`). Uses JSON `lemma` field as override for `lemmatize_word()` — when Claude judges a derivational adjective (`blundering` adj.) should not be reduced to its verbal root (`blunder` v.), the JSON lemma takes precedence. Validates entries before sync: sentence contains target word, IPA format, definition sanity; hard errors block sync, soft warnings print to stderr |
| `ankiconnect.py` | AnkiConnect JSON-RPC client library |
| `filter_pipeline.py` | Combined filter pipeline (Step 1d+1e+1f merged): clean punctuation/case → lemmatize → Anki dedup → COCA check in a single Python invocation. Strips sentence-boundary punctuation (`vexed.`→`vexed`) and normalizes case (`Clad`→`clad`) before processing — eliminates Claude round-trip data transfer, ~0.5s vs previous ~33s. Anki dedup checks surface forms first then lemmas — prevents re-processing words whose surface form already exists as a card (e.g. `blundering` card with WordId `blundering_{bookId}` won't be missed when pipeline lemmatizes to `blunder` and looks for `blunder_{bookId}`) |
| `coca_freq.txt` | COCA word-form frequency list (18,964 entries, frequency-ranked). Single data source for both `load_coca()` set lookup and `load_freq_ranked()` frequency-tier filtering. Frequency lookup via `lib/coca.py` with three-tier strategy: direct set → lemminflect → suffix stripping |
| `scripts/match_sentences.py` | Step 3.0 mechanical sentence matching — reads `filter_fulltext.py` JSON output + source text, extracts one sentence per word with `<b>` tagging. Enforces SKILL.md 3.0e truncation rules (never cut from start, never produce fragments). Replaces Claude manual recall with mechanical matching |
| `scripts/translate_deepl.py` | Step 3.0f DeepL translation — reads vocab-anki JSON, strips `<b>` tags, batch-translates sentences via DeepL API (free tier), writes translations back. Eliminates Claude translation hallucination and post-truncation misalignment. Requires `DEEPL_API_KEY` env var |

**Dependencies:** `weread-skills` (for highlight data via WeRead API), Python packages: `edge-tts`, `lemminflect`

**Design principles:**
- **Separation of concerns**: knowledge work (Claude) vs mechanical work (Python)
- **Filter-first**: all mechanical filtering (Anki dedup, COCA frequency check) happens BEFORE Claude generates content, avoiding wasted effort
- **Anki-before-COCA**: Anki dedup runs before COCA frequency check. Words already in Anki are preserved regardless of COCA frequency changes; COCA only filters truly new words
- **Surface-form-aware dedup**: Anki dedup checks both surface forms AND lemmas against existing cards. Surface forms first (catches cases where sync_anki wrote a derivational adj like `blundering` directly as the WordId), then lemmas (existing behaviour for inflectional forms like `pondered`→`ponder`). Same-book same-surface-form can only have one POS, no false positives
- **JSON lemma override**: `lemmatize_word()` uses VERB/NOUN channels only — it treats all `-ing`/`-ed` forms as verb participles, including derivational adjectives (`blundering` adj.→`blunder` v., `conceited` adj.→`conceit` n.). Claude determines the correct lemma from context: inflectional forms reduce to root (`pondered`→`ponder`), derivational adjectives keep their surface form (`blundering`→`blundering`). The JSON `lemma` field overrides `lemmatize_word()` in `sync_anki.py`
- **Claude quality self-review**: per-batch checklist after writing JSON — lemma correctness (inflectional vs derivational), IPA alignment to lemma, definition POS alignment to contextual usage, word field consistency with `<b>` text, and semantic-context alignment (verify definition/translation captures the correct sense for the specific sentence, not the most common dictionary sense). Catch and fix errors before proceeding to next batch
- **Sentence verification (Step 3.0c-1)**: after mechanically matching a sentence from source text, confirm the target word's surface form actually appears in the sentence (case-insensitive). If source text is unavailable → skip the batch, do not generate cards
- **Derivational adj COCA review**: `lemmatize_word` reduces derivational adjectives to roots that pass COCA (`blundering`→`blunder`). Claude checks: if the word is a derivational adj and its surface form is not directly in COCA 20000 → exclude with reason "派生形容词，不在 COCA 20000 中"
- **Card alignment**: card Word = lemma → IPA corresponds to lemma → audio reads lemma → definition reflects contextual usage. All four aligned. `word` field stores surface form solely for `<b>` tag matching and sentence validation
- **Two-tier lemmatization**: `filter_fulltext.py` calls `build_spacy_map(text)` once to parse the full book text with spaCy (POS-aware, handles ALL irregular/regular/comparative/derivational forms correctly — zero false positives vs ADJ channel). The resulting `{surface → lemma}` map is passed to `lemmatize()` for O(1) lookup. When spaCy is unavailable, `lemmatize()` falls back to lemminflect VERB+NOUN channels with COCA validation. `sync_anki.py` has its own `resolve_lemma()` using lemminflect + COCA gating + spaCy sentence-level POS check for derivational adjectives. No hand-maintained IRREG dict — everything delegated to professional libraries.
- **bookId bridging**: `WordId = {lemma}_{bookId}` enables precise Anki ↔ WeRead matching without relying on book titles (which may differ between Chinese/English).
- **Source-truth-only sentences**: never fabricate a sentence and attribute it to a specific book. Book sentences must come from mechanically matched source text (Step 3.0). If source text is unavailable → skip the batch. Claude's memory for book sentences is unreliable — audit of The Old Man and the Sea deck (2026-06-30) found **245/327 (75%)** sentences were confabulated yet grammatically and thematically plausible. The stroke card had "He took a stroke with the oar" — stroke only appears as "strokes" in the book, describing a tuna's tail, not rowing
- **Single confirmation**: only one user prompt at the end (before sync); intermediate steps report progress without asking
- **Cross-book independence**: same word from different books coexists as independent cards via WordId
- **IPA display-only audio**: Claude provides IPA for card display; IPA corresponds to lemma (card display word), not surface form. Word audio uses Edge TTS reading the lemma text — naturally aligned with IPA since both target the lemma. SSML `<phoneme>` not supported (`edge_tts.Communicate` internally `escape()`s input then wraps in its own `<speak>` via `mkssml()`, causing external SSML to be double-escaped). IPA missing → skip word audio gracefully
- **Graceful degradation**: audio failures don't block card generation
- **Incremental safety**: sync mode only adds, never modifies existing cards
- **Source text retrieval (Step 3.0)**: sentences are extracted from web-sourced book text via mechanical word matching — no longer rely on Claude recall. Eliminates fabricated sentences (e.g., attributing a word to the wrong passage). Extracted sentences must be grammatically complete (subject + finite verb); noun phrase fragments are rejected. Truncation for >150 char sentences preserves main clause integrity — never produces fragments. Falls back to recall mode only when source text is unavailable, with explicit disclaimer in Step 4 summary
- **Per-word timeout**: each word has a 30s timeout (`--word-timeout` flag); on timeout the word is skipped and sync continues; 3 consecutive timeouts abort the sync with a summary of failed words
- **Text progress output**: plain text progress `i/N label` (in-place `\r` on real TTY, line-by-line when piped/captured; no `-v` needed); no graphical bar characters since Claude Code can't render `\r`; verbose mode adds audio source details and byte counts; media upload progress shown in same format
- **Background execution for large syncs**: when word count ≥30, run sync in background (`run_in_background: true`) with `python -u` (unbuffered) to avoid blocking the conversation for several minutes; read the output file after completion to show results
- **Auto deck naming**: deck name auto-derived as `{book_title} ({book_author})`
- **Single-pass filter pipeline**: Step 1 runs `filter_pipeline.py` — one Python invocation that pipelines lemmatize → Anki dedup → COCA check. All data flows through stdin/stdout between processes; Claude never carries tab-separated word lists in echo commands. Eliminates the prior ~33s Claude round-trip overhead (capture output → regenerate as echo → re-parse) down to ~0.5s
- **JSON output via Python json.dump**: Step 3 JSON output prefers Python `json.dump` over `Write` tool — avoids Unicode quote normalization issues (Write tool may normalize Chinese curly quotes `""` to ASCII `"`, breaking JSON). Python `json.dump` with `ensure_ascii=False` preserves Chinese text correctly. Fallback to Write tool only when translations contain no special Unicode quotes
- **Batched content generation**: for >20 words, write JSON in batches of ~15-20 words using Python json.dump (preferred) or `Edit` to append to the `words` array. First batch: full JSON skeleton + first batch. Subsequent batches: `Read limit=5` → `Edit` appends new words before `  ],\n  "excluded"`. **Critical**: after pipeline output, first run Step 3.0 to fetch source text and mechanically extract all sentences. Then write JSON with pre-extracted sentences — no recall needed. Batch writing focuses on IPA + definitions + translations only; per-batch ~5-8s, total ~15-30s

## Testing

- **Every bug fix must include a unit test** that reproduces the failure before the fix is applied. Tests live in `vocab-anki/tests/` (pytest, 231 tests).
- **LLM output quality issues** (definitions, translations, POS classification) are tested via `test_validation.py` — the validator is tested with intentionally bad data simulating historical Claude mistakes. The test verifies the validator catches the error, not that the LLM produces correct output.
- **Python code bugs** (lemmatization, COCA lookup, chapter parsing) are tested directly with parametrized input/output assertions.
- Run `cd vocab-anki && .venv/bin/python -m pytest tests/ -v` before committing.

## Integration

This repo's skills integrate with the `weread-skills` skill (installed from `Tencent/WeChatReading`) for WeRead API access. Skills reuse the same gateway URL, auth header (`Authorization: Bearer $WEREAD_API_KEY`), and flat JSON parameter conventions.

## License

Apache License 2.0 — all contributions are under this license.
