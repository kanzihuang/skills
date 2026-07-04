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

Generate Anki vocabulary flashcard decks from WeRead (微信读书) English book highlights. **Highlight mode only** — for full-text extraction use vocab-book.

**Architecture:** Claude ↔ Python two-phase design:
- **Claude**: knowledge work — extracts sentences from web-sourced book text, provides Chinese definitions, translations, and IPA
- **Python**: mechanical work — lemmatizes words, generates word/sentence TTS via Edge TTS, syncs to Anki via AnkiConnect

**Scripts (skill-specific):**
| Script | Purpose |
|--------|---------|
| `filter_pipeline.py` | Combined filter pipeline — clean punctuation/case → lemmatize → Anki dedup → COCA check |

**Shared scripts (in `lib/`):**
| Script | Purpose |
|--------|---------|
| `lib/sync_anki.py` | Incremental sync to Anki via AnkiConnect |
| `lib/ankiconnect.py` | AnkiConnect JSON-RPC client library |
| `lib/utils.py` | Shared utilities: lemmatize_word, edge_tts_bytes/file, safe_filename, print_progress |
| `lib/scripts/match_sentences.py` | Mechanical sentence matching with `<b>` tagging |
| `lib/scripts/translate_deepl.py` | DeepL batch translation with context support and sentence dedup |
| `lib/scripts/audit_deck.py` | Deck quality audit |
| `lib/SHARED_WORKFLOW.md` | Shared workflow steps (2A–2H) with vocab-book |

**Dependencies:** `weread-skills`, Python: `edge-tts`, `lemminflect`

### vocab-book (`vocab-book/`)

Extract vocabulary from any English book's full text, generate Anki flashcard decks with BNC/COCA frequency banding. **Does NOT depend on WeRead.** UUID suffix isolates cards from other decks.

**Architecture:** Claude ↔ Python two-phase design (same as vocab-anki).

**Scripts (skill-specific):**
| Script | Purpose |
|--------|---------|
| `filter_fulltext.py` | Full-text filter pipeline — spaCy POS tagging → lemminflect per-channel (ADJ/VERB/NOUN) → COCA range filter + level annotation. spaCy health auto-repair on startup. Generates UUID suffix. No AnkiConnect dependency |

**Shared scripts:** Same `lib/` scripts as vocab-anki.

**Dependencies:** Python: `edge-tts`, `lemminflect`, `spacy`

### lib (`lib/`)

Shared Python package and data files used by vocab-anki, vocab-book, and vocab-list.

| File | Purpose |
|------|---------|
| `coca.py` | BNC/COCA word family lookup (Nation 2017), 3-tier strategy |
| `lemmatize.py` | Two-tier lemmatization (spaCy POS gate, lemminflect fallback). Used by vocab-list; vocab-book uses spaCy per-token POS + lemminflect directly in filter_fulltext.py |
| `ankiconnect.py` | AnkiConnect JSON-RPC client |
| `utils.py` | Shared utilities: TTS, lemmatize_word, safe_filename, print_progress |
| `sync_anki.py` | Main sync orchestrator (uses relative imports from lib package) |
| `scripts/` | Shared entry-point scripts (match_sentences, translate_deepl, audit_deck) |
| `data/bnc_coca/` | Nation (2017) word family lists (25 levels × ~1000 families) |
| `data/cmudict.dict` | CMU Pronouncing Dictionary (135K entries) |
| `tests/` | Shared pytest suite (~237 tests) for lib modules |
| `SHARED_WORKFLOW.md` | Shared Claude workflow steps (3.0–4) referenced by both SKILL.md files |

## Shared Design Principles

See `SKILL.md` files and `lib/SHARED_WORKFLOW.md` for full details. Key principles:

- **Separation of concerns**: Claude does knowledge work (sentences, definitions, IPA heteronym voting), DeepL does mechanical translation, Python does mechanical work (lemmatization, TTS, Anki sync).
- **Source-truth-only sentences**: Book sentences come from mechanically matched source text (Step 2A). No fabricated or dictionary sentences. Source text unavailable → skip the batch.
- **Source-truth-only translations**: Translations must be of the mechanically matched sentence. Never substitute a translation from memory even if you recognize the passage — this causes sentence/translation mismatch.
- **Incremental safety**: sync mode only adds, never modifies existing cards.
- **Graceful degradation**: audio failures don't block card generation.
- **Filter-first**: all mechanical filtering happens BEFORE Claude generates content.
- **POS-gated lemmatization (vocab-book)**: spaCy provides POS tags; lemminflect provides lemmatization. Per-token POS→channel matching (ADJ/VERB/NOUN) — spaCy's lemma output is never used. Proper nouns and derivational adjectives are kept as-is. VBG+amod (participial adjectives like "bewildering") are guarded against reduction.
- **Truncate before translate**: sentence truncation (≤250 chars) must complete before DeepL/Claude translation. Never translate then truncate — causes sentence/translation mismatch. Verification: Chinese translation must not end with conjunctions like "然后"/"但是".
- **bookId bridging (vocab-anki)**: `WordId = {lemma}_{bookId}` enables precise Anki ↔ WeRead matching.
- **IPA from cmudict**: IPA is generated mechanically from the CMU Pronouncing Dictionary. Stress placement follows Maximal Onset Principle. ER0 (unstressed) → /ər/, ER1/ER2 → /ɜːr/. Claude only votes on heteronym disambiguation.

## Testing

- **Every bug fix must include a unit test** that reproduces the failure before the fix is applied.
- **Shared tests** live in `lib/tests/` (pytest, 259 tests) — covers coca, lemmatize, utils, sync_anki, validation, auto_band, match_sentences.
- **Skill-specific tests**: `vocab-anki/tests/` (filter_pipeline, 23 tests), `vocab-book/tests/` (filter_fulltext, 10 tests).
- **LLM output quality issues** are tested via `test_validation.py` — the validator catches intentional bad data, not LLM output.
- **Python code bugs** are tested directly with parametrized input/output assertions.
- Run all tests before committing:
  ```bash
  cd lib && /home/agent/.claude/skills/vocab-anki/.venv/bin/python -m pytest tests/ -v && \
  cd ../vocab-ani && .venv/bin/python -m pytest tests/ -v && \
  cd ../vocab-book && ../vocab-anki/.venv/bin/python -m pytest tests/ -v
  ```

## Integration

- `vocab-anki` integrates with `weread-skills` (Tencent/WeChatReading) for WeRead API access.
- `vocab-book` has no external skill dependencies.
- Both reuse the shared `lib/` package for COCA lookup, lemmatization, AnkiConnect, and sync.

## Package Skills

```bash
bash scripts/package_skill.sh [output_dir]
```
Creates self-contained zip files for each skill, embedding required `lib/` modules.

## License

Apache License 2.0 — all contributions are under this license.
