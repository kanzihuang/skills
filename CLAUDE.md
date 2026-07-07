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
| `lib/scripts/match_sentences.py` | Sentence matching + per-sentence spaCy POS analysis + (lemma,pos) grouping + cmudict IPA |
| `lib/scripts/translate_deepl.py` | DeepL batch translation with context support and sentence dedup |
| `lib/scripts/audit_deck.py` | Deck quality audit |
| `lib/SHARED_WORKFLOW.md` | Shared workflow steps (2A–2H) with vocab-book |

**Dependencies:** `weread-skills`, Python: `edge-tts`, `lemminflect`, `deepl`

### vocab-book (`vocab-book/`)

Extract vocabulary from any English book's full text, generate Anki flashcard decks with BNC/COCA frequency banding. **Does NOT depend on WeRead.** UUID suffix isolates cards from other decks.

**Architecture:** Claude ↔ Python two-phase design (same as vocab-anki).

**Scripts (skill-specific):**
| Script | Purpose |
|--------|---------|
| `filter_fulltext.py` | Full-text COCA filter — spaCy tokenization, surface-form-only `in_coca()` lookup, COCA range + level annotation. No lemmatization. Generates UUID suffix. No AnkiConnect dependency |

**Shared scripts:** Same `lib/` scripts as vocab-anki.

**Dependencies:** Python: `edge-tts`, `lemminflect`, `spacy`, `deepl`

### lib (`lib/`)

Shared Python package and data files used by vocab-anki, vocab-book, and vocab-list.

| File | Purpose |
|------|---------|
| `coca.py` | BNC/COCA word family lookup (Nation 2017), 3-tier strategy |
| `lemmatize.py` | Two-tier lemmatization (spaCy POS gate, lemminflect fallback). Used by vocab-list and sync_anki.py fallback path |
| `ankiconnect.py` | AnkiConnect JSON-RPC client |
| `utils.py` | Shared utilities: TTS, lemmatize_word, safe_filename, print_progress |
| `sync_anki.py` | Main sync orchestrator (uses relative imports from lib package) |
| `scripts/` | Shared entry-point scripts (match_sentences, translate_deepl, audit_deck) |
| `data/bnc_coca/` | Nation (2017) word family lists (25 levels × ~1000 families) |
| `data/cmudict.dict` | CMU Pronouncing Dictionary (135K entries) |
| `tests/` | Shared pytest suite (~359 tests) for lib modules |
| `SHARED_WORKFLOW.md` | Shared Claude workflow steps (2A–2H) referenced by both SKILL.md files |

## Shared Design Principles

See `SKILL.md` files and `lib/SHARED_WORKFLOW.md` for full details. Key principles:

- **Separation of concerns**: Claude does knowledge work (sentence review, definitions, IPA for heteronyms/cmudict misses), DeepL does mechanical translation, Python does mechanical work (POS analysis, lemmatization, TTS, Anki sync, cmudict IPA).
- **Source-truth-only sentences**: Book sentences come from mechanically matched source text (Step 2A). No fabricated or dictionary sentences. Source text unavailable → skip the batch. Sentence selection is also mechanical: `match_sentences.py` scans sentences once (not per-word), does per-sentence spaCy POS analysis, and incrementally updates the best candidate per (lemma,pos) via `_better()` (three-tier XOR comparison: sweet-spot 30-250 > long > very-short). No candidates accumulation.
- **Source-truth-only translations**: Translations must be of the mechanically matched sentence. Never substitute a translation from memory even if you recognize the passage — this causes sentence/translation mismatch.
- **Incremental safety**: sync mode only adds, never modifies existing cards.
- **Graceful degradation**: audio failures don't block card generation.
- **Filter-first**: all mechanical filtering happens BEFORE Claude generates content.
- **Per-sentence POS-gated lemmatization**: `match_sentences.py` runs spaCy on each selected sentence to determine POS and lemma. Multi-signal adjective detection (POS=ADJ, adjectival dep, VBG+amod, be-to pattern, spacy_lemma==word, PROPN guard, -ly adverb guard). Falls through to lemminflect with the correct POS channel. No global voting — POS is determined from the specific sentence context. Claude does NOT set lemma (it is mechanically authoritative).
- **Truncate before translate**: sentence truncation (≤250 chars) must complete before DeepL/Claude translation. Never translate then truncate — causes sentence/translation mismatch.
- **bookId bridging (vocab-anki)**: `WordId = {lemma}_{pos}_{bookId}` enables precise Anki ↔ WeRead matching and prevents cross-POS collisions.
- **WordId isolation (vocab-book)**: `WordId = {lemma}_{pos}_{suffix}` — UUID suffix isolates cards from other batches; POS prevents same-lemma different-POS collisions.
- **IPA from cmudict**: IPA is generated mechanically by `match_sentences.py` from the CMU Pronouncing Dictionary. Claude only provides IPA for cmudict misses and heteronym disambiguation.

## Known Pitfalls & Troubleshooting

Common failure modes discovered through production use. Reference when debugging deck quality issues.

### Step 2B/2F 不可绕过

Step 2B（句子选择+截断）和 Step 2F（内容验证）是质量门禁，即使 match_sentences.py 预选结果看起来完美也不可跳过。只有 Claude 能识别：
- 序言/非正文句子（char_offset 靠前、内容为作者简介/编辑导语）
- 定义质量（如一词多译时的不一致）
- 翻译-释义对齐

自动检查（validation.py）只做格式校验，不做语义校验。每步执行后运行 check_step_completed.py 验证。

### Lemmatizer false positives (ADV channel)

`lemmatize_word()` uses lemminflect's VERB → NOUN → ADJ → ADV channels. The ADV channel produces false positives for non-adverb words: "absurd"→"absur" (treats 'd' as comparative suffix), "reflective"→"reflect" (treats 'ive' as adverb suffix). **Fix (2026-07-05)**: ADV channel now gated to words ending in -ly only.

### Lemmatizer false positives (suffix rules, -est/-er)

`lemmatize()` Step 3 (suffix rules) reduces words by stripping -est/-er/-ier/-iest suffixes. Before the fix (2026-07-06), Step 3 returned immediately (`return cand`), bypassing Step 4 (spaCy map) and Step 6 (Nation cross-validation). This caused:

- **forest→fore**: "forest" ends in "est" → stripped to "for" → dropped-e rule adds "e" → "fore". spaCy map has correct answer but Step 3 returned before Step 4 ran.
- **forever→forev**: "forever" not in COCA → -er stripped → "forev" (not a real word). Pytest's spacy_map didn't include "forever", and Nation list doesn't have "forever" as a headword.

**Fix (2026-07-06)**: Three changes:
1. Step 3 stores candidate in `suffix_candidate` instead of returning — lets later steps (spaCy map, Nation) validate
2. COCA plausibility gate: candidate must be a real English word (`cand in coca_set`) before Step 3 accepts it — rejects "forev"
3. Step 5 inherits `suffix_candidate` as initial value: `reduced = suffix_candidate or w`

Symptom: deck has cards with Word="fore" (should be "forest") or "forev" (should be "forever"). Check: `grep -E '^fore|^forev'` in filter output.

### DeepL translation now runs before Claude definitions

**Change (2026-07-06)**: Step 2D (DeepL) and Step 2E (Claude definitions) swapped — translation now completes before Claude generates `definition_cn`. This gives Claude the Chinese translation as context for word-sense disambiguation. Step 2F (validation) adds a `definition_cn ↔ translation_cn` consistency check.

### DeepL failure handling

**Change (2026-07-06)**: `translate_deepl.py` now classifies exceptions and retries smartly:
- Network/429 → retry with context
- 4xx (possible context issue) → retry without context
- Auth/Quota → immediate `sys.exit(1)`
- All failures after 1 retry → `sys.exit(1)` hard abort

Symptom: COCA-valid words get excluded by filter_pipeline (absurd→absur not in COCA) or get wrong IPA (reflective→reflect IPA).
Check: `python3 -c "import lemminflect; print(lemminflect.getLemma('WORD', 'ADV'))"` — if it returns a shorter non-word, it's this bug.

### Source text OCR artifacts (double spaces)

Internet Archive `.txt` files often contain double-space OCR artifacts. `match_sentences.py` now normalizes whitespace, but if sentences from other sources have double spaces, verify the source text quality first. Use `grep -c '  ' source.txt` to check.

### `<b>` tags added at sync time

**Change (2026-07-07)**: Sentences are stored WITHOUT `<b>` tags in the JSON. `sync_anki.py` inserts `<b>` tags at display time using `target_offset`. Sentence-initial capitalization (e.g. "Absurd") is preserved in the sentence text; the `word` field stores the canonical lowercase form. Validation checks `target_offset` instead of parsing `<b>` tags.

### Lemma is now mechanical — Claude does NOT set lemma

**Change (2026-07-07)**: Lemma is determined by `match_sentences.py` from per-sentence spaCy POS analysis + lemminflect. Claude no longer participates in lemma decisions (Step 2D/2E). The `lemma` field in the JSON must not be modified by Claude.

### Deck name is auto-derived — Claude does NOT set deck_name

**Change (2026-07-07)**: Deck name is auto-derived by `sync_anki.py`'s `_derive_deck_name()` from `book_title` + `book_author` + "分级词汇" suffix. Claude must NOT set `deck_name` in the JSON or pass `--deck` on the CLI — doing so overrides the correct auto-generated name. The format is `{title} ({author}) - 分级词汇` for vocab-book, `{title} ({author})` for vocab-anki.

### Exact-form-only sentence matching

`match_sentences.py` searches for the **exact surface forms** from the `forms` array in the source text. No inflectional expansion (-s/-es/-ed/-ing). If a user highlights the base form ("arouse") but the text only has inflected forms ("aroused"), the word gets no sentence → excluded from the deck. This is by design: the card's `<b>` tag must wrap the exact word the user highlighted. Do not manually expand forms to force a match.

### Truncation vs editing (截断 ≠ 改编)

Step 2B truncation must produce **continuous substrings** of the source text — delete from beginning/end only, never replace/edit words in the middle. Editing (e.g., "And then look:" → "Look:") breaks regex matching in `translate_deepl.py`, silently losing DeepL context.

**Fix (2026-07-05)**: Step 2B post-truncation self-checks now include Step 0 — `_build_sentence_regex(truncated)` must match the source text. Failure → rejection, redo the truncation.

**Verify**: after truncation, run `_build_sentence_regex(sentence)` against source sentences. Match → continuous substring ✓. No match → editing detected ✗.

### Intra-batch duplicate WordId → audio collision + sentence overwrite

Two words that lemmatize to the same root (e.g. "boa" + "boas" → both "boa") produce the same WordId, same audio filename (`boa_{suffix}_sent.mp3`), and same card. Before the fix (2026-07-06), `add_new_cards()` only deduplicated against Anki's existing cards — not against other words in the same batch. This caused:
- The second word's sentence audio **overwrites** the first word's audio file (same filename)
- The Anki card's Sentence field gets the **second** word's sentence (last write wins)
- Result: card shows word="boa" but sentence has `<b>boas</b>` — mismatch, wrong audio

**Fix (2026-07-06)**: Added `seen_word_ids` set in `add_new_cards()` — tracks WordIds within the current batch. First occurrence wins, subsequent duplicates are skipped BEFORE audio generation. Regression test: `TestIntraBatchDedup` (4 tests) in `test_sync_note.py`.

Symptom: card's Word field ≠ `<b>` text in Sentence field, sentence audio doesn't match displayed text. Check: `grep -c '_sent\.mp3' manifest.json` vs actual card count — duplicate filenames mean collision.

### POS analysis is per-sentence, not global voting

**Change (2026-07-07)**: `match_sentences.py` runs spaCy on each selected sentence (not the full text). POS is determined from the specific sentence context, not aggregated via majority vote. Lowercase PROPN tokens are treated as NOUN for lemmatization. `build_spacy_map()` is no longer used.

### WordId includes POS for cross-POS collision prevention

**Change (2026-07-07)**: `WordId = {lemma}_{pos}_{suffix}` (vocab-book) or `{lemma}_{pos}_{bookId}` (vocab-anki). POS is included to prevent collisions when the same lemma appears with different parts of speech (e.g. "walk" as NOUN vs VERB).

## Testing

- **Every bug fix must include a unit test** that reproduces the failure before the fix is applied.
- **Shared tests** live in `lib/tests/` (pytest, 382 tests) — covers coca, lemmatize, utils, sync_anki, validation, auto_band, match_sentences.
- **Skill-specific tests**: `vocab-anki/tests/` (filter_pipeline, 32 tests), `vocab-book/tests/` (filter_fulltext, 12 tests).
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
