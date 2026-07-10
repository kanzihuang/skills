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
| `lib/scripts/extract_chapter.py` | Chapter extraction with `--boundaries-file` option for books without headings |
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
| `audio.py` | Anki media directory detection + direct filesystem media upload |
| `bands.py` | COCA frequency band computation for sub-deck splitting |
| `chapter_detect.py` | Chapter heading detection + preamble skip; used by match_sentences and extract_chapter |
| `config.py` | Centralized constants (MAX_SENTENCE_LENGTH, Edge TTS retries, timeouts) |
| `ipa.py` | cmudict ARPAbet→IPA conversion with suffix-stripping fallback |
| `utils.py` | Shared utilities: TTS, lemmatize_word, safe_filename, print_progress |
| `sync_anki.py` | Main sync orchestrator (uses relative imports from lib package) |
| `scripts/` | Shared entry-point scripts (match_sentences, translate_deepl, audit_deck, extract_chapter) |
| `data/bnc_coca/` | Nation (2017) word family lists (25 levels × ~1000 families) |
| `data/cmudict.dict` | CMU Pronouncing Dictionary (135K entries) |
| `tests/` | Shared pytest suite (285 tests) for lib modules |
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
- **No hard-coded semantic word lists in Python**: Python code handles mechanical/formal work (tokenization, regex, IPA lookup, COCA level mapping). Semantic classification — distinguishing emotional adjectives from true passives, heteronym disambiguation, identifying non-body-text sentences — is Claude's responsibility in the mandatory review gates (Step 2B, Step 2F). Hard-coded word sets create unbounded maintenance burden and violate separation of concerns.

## Known Pitfalls & Troubleshooting

Common failure modes discovered through production use. Reference when debugging deck quality issues.

### Step 2B/2F 不可绕过

Step 2B（句子选择+截断）和 Step 2F（内容验证）是质量门禁，即使 match_sentences.py 预选结果看起来完美也不可跳过。只有 Claude 能识别：
- 序言/非正文句子（char_offset 靠前、内容为作者简介/编辑导语）
- 定义质量（如一词多译时的不一致）
- 翻译-释义对齐

**Step 2B pre-pass**: Run `smart_truncate()` mechanically before manual review to
handle the 80% case (tail-truncate at sentence boundaries).  Claude then only
reviews entries still marked `_needs_manual`.  See `lib/SHARED_WORKFLOW.md` Step 2B-0.

自动检查（`validation.py`，可由 `sync_anki.py` 内部调用或独立运行 `python -m lib.validation <json>`）只做格式校验，不做语义校验。每步执行后运行 check_step_completed.py 验证（支持 `--step 2B`, `--step 2B-verify`, `--step 2E`, `--step 2F`, `--step 2F-dup`, `--step all`）。

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

**Change (2026-07-06)**: Step 2C (DeepL) and Step 2E (Claude definitions) swapped — translation now completes before Claude generates `definition_cn`. This gives Claude the Chinese translation as context for word-sense disambiguation. Step 2F (validation) adds a `definition_cn ↔ translation_cn` consistency check.

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

**Change (2026-07-07)**: Lemma is determined by `match_sentences.py` from per-sentence spaCy POS analysis + lemminflect. Claude no longer participates in lemma decisions (Step 2C/2E). The `lemma` field in the JSON must not be modified by Claude.

### Deck name is auto-derived — Claude does NOT set deck_name

**Change (2026-07-07)**: Deck name is auto-derived by `sync_anki.py`'s `_derive_deck_name()` from `book_title` + `book_author` + "分级词汇" suffix. Claude must NOT set `deck_name` in the JSON or pass `--deck` on the CLI — doing so overrides the correct auto-generated name. The format is `{title} ({author}) - 分级词汇` for vocab-book, `{title} ({author})` for vocab-anki.

### Exact-form-only sentence matching

`match_sentences.py` searches for the **exact surface forms** from the `forms` array in the source text. No inflectional expansion (-s/-es/-ed/-ing). If a user highlights the base form ("arouse") but the text only has inflected forms ("aroused"), the word gets no sentence → excluded from the deck. This is by design: the card's `<b>` tag must wrap the exact word the user highlighted. Do not manually expand forms to force a match.

### Truncation vs editing (截断 ≠ 改编)

Step 2B truncation must produce **continuous substrings** of the source text — delete from beginning/end only, never replace/edit words in the middle. Editing (e.g., "And then look:" → "Look:") breaks regex matching in `translate_deepl.py`, silently losing DeepL context.

**Fix (2026-07-05)**: Step 2B post-truncation self-checks now include Step 0 — `build_sentence_regex(truncated)` (from `lib.utils`) must match the source text. Failure → rejection, redo the truncation.

**Verify**: after truncation, run `build_sentence_regex(sentence)` (`from lib.utils import build_sentence_regex`) against source sentences. Match → continuous substring ✓. No match → editing detected ✗.

**Known exception — OCR compound-word hyphenation repair**: `build_sentence_regex` may produce false negatives when Step 2B fixes OCR spacing around hyphens in compound words (e.g., `"fair-to- middling"` → `"fair-to-middling"`). The fixed sentence has one token (`fair-to-middling`) but the source text still has the space-separated original (`fair-to- middling`). The regex `fair\-to\-middling` cannot match across the space. When the only difference is hyphen-space normalization, verify with `fixed_sentence.replace('- ', '-').replace(' -', '-') in source_text` instead. See `lib/SHARED_WORKFLOW.md` Step 2B for details.

### Blank-line sentence fragmentation (PySBD + source text artifacts)

When source text contains blank lines within a sentence (e.g. `"bigger \n\n\n\nthan himself"`), PySBD treats `\n\n` as a sentence boundary, splitting the sentence into fragments. `_normalize_dialogue_attribution()` handles `[:,]\n{2,}["""]` (attribution→dialogue), but does not cover blank lines within sentences without attribution markers.

**Fix (2026-07-08)**: `match_sentences.py` now marks fragment candidates with `is_fragment=True` (via `_is_fragment()` — detects missing sentence-ending punctuation, unclosed quotes, lowercase starts). `_better()` Tier 0 deprioritizes fragments: a complete sentence always beats a fragment; if the only candidate is a fragment, it still wins (to avoid data loss). `check_step_completed.py --step 2B` flags sentences lacking terminating `. ! ?`. Step 2B provides a manual repair workflow in `SHARED_WORKFLOW.md`.

**Fix (2026-07-09)**: `_merge_adjacent_fragments()` automatically merges most fragments.
When `split_sentences()` is called with `source_text`, adjacent fragment pairs are
merged and verified as continuous substrings of the source via `build_sentence_regex()`.
Step 2B manual repair is only needed for fragments that cannot be auto-merged.

Symptom: `is_fragment=True` in match_sentences output for a word; `check_step_completed.py` warns about lacking terminating punctuation. Check: `grep '"is_fragment": true'` in match_sentences output. If the word only appears once in the text (no other sentence to select), the fragment is still kept — fix it in Step 2B.

### Lemma case normalization at output

**Change (2026-07-08)**: Non-PROPN lemmas are now lowercased at output time (`match_sentences.py:578`): `cand['lemma'] if cand['pos'] == 'PROPN' else cand['lemma'].lower()`. The group key also lowercases (`(lemma.lower(), pos)`) to merge same-word different-casing entries. Previously, `_determine_lemma():157` returned capitalized lemmas for mid-sentence PROPN tokens, which after PROPN→NOUN conversion produced `"Asteroid"` vs `"asteroid"` — two separate entries for the same word, later merged by `sync_anki.py`'s dedup with a surprise card count drop.

Symptom: fewer cards than expected (e.g., 23 vs 24); capitalized and lowercase lemmas for the same word. Check: `grep -E '"lemma": "[A-Z]'` in match_sentences output for non-PROPN entries.

### Intra-batch dedup key: (lemma, pos) not surface word form

**Change (2026-07-08)**: The intra-batch dedup key was changed from `w["word"]` (surface form) to `(w["lemma"], w["pos"])`. Using surface form caused same-lemma different-POS entries (e.g. `astray` ADJ vs ADV, `virgin` ADJ vs NOUN) to be incorrectly merged into one card. WordId = `{lemma}_{pos}_{suffix}` — POS is included precisely to prevent this.

Symptom: fewer cards than expected; `astray` ADJ+ADV → only one card. Check: count unique (lemma, pos) pairs vs actual card count.

### Audio filename includes POS to prevent cross-POS collision

**Change (2026-07-08)**: Audio filenames changed from `{lemma}_{suffix}_word/sent.mp3` to `{lemma}_{POS}_{suffix}_word/sent.mp3`. Previously, same-lemma different-POS entries (e.g. `astray` ADJ vs ADV) shared the same audio filename — the second entry's sentence audio silently overwrote the first. Now each (lemma, pos) gets independent audio files.

Symptom: two cards with same lemma but different POS play the same sentence audio. Check: compare `[sound:...]` references in cards with same lemma.

### Audio filename collision detection (defense-in-depth)

**Change (2026-07-08)**: After dedup, `sync_anki.py` verifies that no two entries share the same audio filename prefix `{safe_filename(lemma)}_{pos}`. A collision means two cards would overwrite each other's audio — this should never happen after correct (lemma,pos) dedup, so a hit signals a bug. Also catches edge cases where different lemmas map to the same `safe_filename` output (e.g. `a/b` and `a b` both → `a_b`).

### be_to detection for modern spaCy (JJ tag support)

**Change (2026-07-08)**: `_has_be_to_pattern()` in `match_sentences.py` previously only accepted VBN-tagged tokens. Modern spaCy models (en_core_web_sm) correctly tag psychological adjectives like "astounded" as JJ/ADJ directly — the VBN gate never fired. Extended to accept both VBN and JJ tags, with JJ gated on predicate-adjective dependency relations (acomp, oprd) only. The caller now computes `has_be_to` unconditionally so `be_to=True` propagates to the output even when `_determine_lemma` already returned the surface form via other ADJ signals.

Symptom: `be_to=False` on entries like "was astounded to hear..." despite clear be+adj+to pattern. Check: `grep '"be_to": false'` in match_sentences output for entries with "was/were/is/are + word + to".

### Dialogue-attribution sentence fragments (colon/comma + blank line)

**Change (2026-07-08)**: Some plain-text editions separate dialogue-attribution lines from their spoken text with blank lines:

```
He looked attentively, then:

"No! That one is already very ill."
```

PySBD splits these at the blank line, producing colon/comma-ending fragments like `"He looked attentively, then:"`. `_normalize_dialogue_attribution()` collapses `[:,]\n\n"` → `\1 "` BEFORE PySBD segmentation, joining the attribution with its dialogue into a complete sentence.

Two-layer defense: (1) source text normalization in `split_sentences()`, (2) validation soft-warns on colon-ending sentences (stderr only, does not block sync). Step 2B provides a third, upstream layer: Claude checks for OCR colon→period errors during sentence review and corrects them before translation. The function-word-ending check in `validation.py` also now strips trailing `:;` from the last word before comparing against `_FUNCTION_ENDINGS`, so `"then:"` correctly matches `"then"`.

Symptom: sentences ending with `:` or `,` that look like dialogue lead-ins (e.g. `"He looked attentively, then:"`). Check: `grep ":'$"` or `grep ",'$"` in match_sentences output.

### POS analysis is per-sentence, not global voting

**Change (2026-07-07)**: `match_sentences.py` runs spaCy on each selected sentence (not the full text). POS is determined from the specific sentence context, not aggregated via majority vote. Lowercase PROPN tokens are treated as NOUN for lemmatization. `build_spacy_map()` is no longer used.

### WordId includes POS for cross-POS collision prevention

**Change (2026-07-07)**: `WordId = {lemma}_{pos}_{suffix}` (vocab-book) or `{lemma}_{pos}_{bookId}` (vocab-anki). POS is included to prevent collisions when the same lemma appears with different parts of speech (e.g. "walk" as NOUN vs VERB).

### attr dep is NOT a reliable ADJ signal

**Change (2026-07-08)**: `attr` (predicate attribute) was removed from the adjectival dependency set in `match_sentences.py` (`_determine_lemma` Signal 2 and main-loop POS correction). `attr` is the complement of copular verbs — it applies equally to nouns ("He is **a teacher**") and adjectives ("He is **tall**"). Unlike `amod`/`acomp`/`oprd` which are exclusively adjectival, `attr` is NOT a reliable ADJ signal.

Before the fix, a NOUN with `attr` dep (e.g. "constrictor" in "It was a boa constrictor") was incorrectly promoted to ADJ because the code treated `attr` identically to `amod`/`acomp`/`oprd`.

`_has_be_to_pattern` already correctly excludes `attr` (it only accepts `acomp`/`oprd` for JJ-tagged tokens) — no change was needed there.

Symptom: entries like "constrictor" tagged ADJ with definition "[adj.] 大蟒的" when it should be NOUN. Check: `grep '"pos": "ADJ"'` in match_sentences output for words that are clearly nouns.

### PROPN→NOUN conversion missed mid-sentence capitalized common nouns

**Change (2026-07-08)**: The PROPN→NOUN POS correction in `match_sentences.py` (main loop) was widened from `token.text[0].islower() or token.i == 0` to also include `token_lower in form_index`. The original condition only caught lowercase PROPNs ("boas") and sentence-initial PROPNs ("Absurd"). It missed mid-sentence capitalized common nouns ("Boa" in "in the book, Boa constrictors swallow...").

Since the code only reaches this check after confirming the word is in our COCA filter, `token_lower in form_index` is a safe signal: any tracked vocabulary word tagged PROPN is a spaCy misclassification — genuine proper nouns are almost never COCA level 4+.

**Caveat — genuine proper nouns in COCA (2026-07-08)**: Some genuine proper nouns ARE in COCA at various levels (e.g. Jupiter L16, Mars L6, Venus L4).  `token_lower in form_index` incorrectly converts them to NOUN.  A revert guard was added: after all POS corrections, if the word was originally PROPN, is now NOUN (no ADJ rules fired), is NOT sentence-initial, and **never appears in all-lowercase anywhere in the source text** — revert it back to PROPN.  The all-lowercase check is a pre-computed set from the source text (`\b[a-z]{2,}\b`), so it's purely mechanical — no hard-coded proper-noun lists.

Words like "Astronomical" (in "International Astronomical Congress") are PROPN→NOUN (form_index match), then promoted to ADJ by the NOUN+compound suffix rule — they never reach the revert guard.

Note: `_determine_lemma` Signal 4 was NOT changed — `word[0].islower()` there refers to `token.text.lower()[0]` which is always lowercase, so it always enters the NOUN lemmatization branch. The lemma was already correct ("boa"); only the POS tag was wrong.

Symptom (false positive): "Jupiter" tagged NOUN instead of PROPN. Check: `grep '"lemma": "jupiter"'` in match_sentences output — if `pos` is NOUN, the word never appears lowercase in the source and the revert guard should fix it.
Symptom (false negative): "Boa" still tagged PROPN. Check: ensure "boa" appears in lowercase elsewhere in the source text. If it only appears capitalized, the revert guard can't distinguish it from a genuine proper noun — add a lowercase occurrence to the source text or accept the PROPN tag.

### PROPN→NOUN revert: proper-noun protection via lowercase-presence check

**Change (2026-07-08)**: After all POS corrections, a revert guard runs: if `_was_propn and pos == "NOUN" and token.i != 0 and token_lower not in _all_lowercase_words` → revert to PROPN.  `_all_lowercase_words` is pre-computed from the source text with `re.findall(r'\b[a-z]{2,}\b', text)` at pipeline start.  Sentence-initial tokens (`token.i == 0`) are exempt from the revert because capitalization may be positional.

The revert runs AFTER the ADJ-promoting rules (NOUN+compound suffix, NOUN/VERB+amod/acomp/oprd), so adjectives in proper-noun phrases ("Astronomical" in "International Astronomical Congress") are correctly promoted to ADJ before the revert check.

Symptom: genuine proper nouns (planet names, person names) tagged NOUN. Check: `grep '"pos": "PROPN"'` in match_sentences output — should be non-zero for texts containing proper nouns.

### Mid-sentence capitalized NOUN→PROPN misclassifies quote-initial common nouns

**Change (2026-07-09)**: The mid-sentence capitalised NOUN→PROPN rule (`not _was_propn and pos == "NOUN" and token.i != 0 and text[0].isupper()`) converts common nouns at quote starts to PROPN (e.g. "Boa" in `said: "Boa constrictors..."`).  spaCy correctly tags these as NOUN, but the rule assumes any mid-sentence capitalised word is a proper noun — it doesn't account for quotation marks.

**Fix**: Added `and token_lower not in form_index` guard.  If the lowercase form of the token is in our target vocabulary, it's a common noun capitalised by position (quote-initial) — not a proper noun.  Genuine proper nouns that spaCy tagged as NOUN (e.g. "Jupiter" without lowercase occurrences) still convert to PROPN because they were already handled by the PROPN→NOUN→revert path.

Symptom: `(boa, NOUN)` + `(boa, PROPN)` duplicate entries for the same word, requiring Step 2F manual dedup.  Check: `grep '"lemma": "boa".*"pos": "PROPN"'` in match_sentences output.

### Curly quote normalisation

**Change (2026-07-09)**: `_normalize_quotes()` normalises Unicode curly quotes (`""''`) to ASCII straight quotes before sentence processing.  Internet Archive OCR texts commonly include curly quotes which propagate through PySBD → spaCy → DeepL into JSON output, causing `json.load()` failures and `check_step_completed.py` rejections.

Symptom: `check_step_completed.py --step all` reports curly quote issues.  Check: `grep -P '[\x{2018}\x{2019}\x{201C}\x{201D}]'` in JSON output.

### ADV→NOUN guard: dep=dobj contradicts ADV

**Change (2026-07-08)**: Added `if pos == "ADV" and token.dep_ == "dobj": pos = "NOUN"` POS correction.  spaCy occasionally mis-tags direct objects as adverbs (e.g. "sprig" in "push a charming little sprig upward").  `dep=dobj` requires a nominal — an adverb cannot be a direct object in Universal Dependencies.  This is a reliable signal of a spaCy POS error.

Guard is conservative: `dep=dobj` is the strongest nominal dependency signal.  Tested against 15+ edge cases — spaCy never produces legitimate ADV+dobj combinations.

Symptom: common nouns tagged ADV in match_sentences output. Check: `grep '"pos": "ADV"'` for words that don't end in -ly and appear as direct objects.

### --start-offset -1 fix: disable preamble detection without text[-1:] slicing

**Change (2026-07-08)**: The `--start-offset` argument's help text says "pass -1 to disable preamble detection", but the code only had `if start_offset == 0:` for preamble detection.  Passing `-1` caused `text[-1:]` slicing (last character only), producing 0 sentences.  Added `elif start_offset < 0: start_offset = 0` branch.

Symptom: 0 sentences found when using `--start-offset -1`. Check: stderr shows "Sentences: 0".

### char_offset now derived from selected sentence, not first global match

**Change (2026-07-08)**: `char_offset` was computed post-hoc by `_first_word_boundary_offset()`, which always returns the FIRST occurrence in the source text.  When a word appears twice and `_better()` selects the sentence from the second occurrence, `char_offset` still pointed to the first.  Fixed by adding `_sentence_char_offset()`: builds a whitespace-tolerant regex from the selected sentence text, searches the source, and computes `char_offset = match_start + target_offset`.  Falls back to `_first_word_boundary_offset()` when sentence-based search fails (edge case: hard truncation or unusual whitespace).

Symptom: `char_offset` points to wrong part of source text (word at that offset doesn't match the sentence). Check: compare `text[char_offset:char_offset+len(word)]` against the entry's `word` field.

### Dialogue-attribution regex: curly quotes + 3+ newlines

**Change (2026-07-08)**: `_DIALOGUE_ATTRIBUTION_RE` was widened from `r'([:,])[ \t]*\n[ \t]*\n[ \t]*"'` to `r'([:,])[ \t]*\n{2,}[ \t]*["“”]'`.  Two gaps fixed: (1) only matched ASCII `"` — added Unicode curly quotes `“` `”` common in Internet Archive OCR texts; (2) only matched exactly 2 newlines — changed to `\n{2,}` to handle 3+ consecutive newlines (the regex runs BEFORE `\n{2,}` normalization in `split_sentences()`).

Symptom: comma/colon-ending sentences surviving to validation despite being obvious dialogue-attribution fragments. Check: `grep ",'$"` or `grep ":'$"` in match_sentences output.

### validation.py check 7e: comma-ending sentences demoted from hard error to soft warning

**Change (2026-07-08)**: Check 7e (punctuation artifact) was split into two tiers: `,[.)]$` pattern stays a hard error (unambiguous OCR debris like "breeze,."); bare `endswith(',')` is now a soft warning (may be a dialogue-attribution fragment that survived normalization, or an OCR artifact — neither should block sync; Step 2B handles the fix).  This matches the existing check 7d which already soft-warns on colon-ending sentences for the same reason.

Symptom: `sync_anki.py` blocked by "punctuation artifact" error on a sentence that looks like dialogue attribution. Check: validation stderr for hard errors on entries ending with bare comma.

### conj POS inheritance for coordinated structures

**Change (2026-07-08)**: `match_sentences.py` main loop now inherits POS from the coordination root for `dep=conj` tokens. spaCy sometimes mis-tags individual conjuncts (e.g. "arithmetic" as ADJ in "geography, history, arithmetic and grammar", where all are NOUNs). The fix walks up the `dep=conj` chain to find the coordination root and inherits its POS when `pos != head_pos` and the root has a reliable POS tag (NOUN/VERB/ADJ/ADV).

Chain-walking is critical: in "A, B, C and D", "D" depends on "C" (conj), "C" depends on "B" (conj), "B" depends on "A" (root). Without walking up, "D" would inherit from "C" which is itself a conjunct — the walk finds "A" as the true coordination root.

Guard: `head_pos in ("NOUN", "VERB", "ADJ", "ADV") and pos != head_pos` — only inherits from content-word roots and only when POS actually differs. PROPN roots (e.g. "Tom" in "Tom and Jerry") are not in the whitelist, so PROPN conjuncts stay unchanged.

Symptom: "arithmetic" tagged ADJ in a noun list. Check: `grep '"pos": "ADJ"'` in match_sentences output for words in noun coordination.

### spaCy xcomp VERB mis-tag for nouns after "contrary to" (NOT mechanically fixable)

spaCy systematically mis-parses nouns in "contrary/adjective + to + NOUN + to VERB"
constructions (e.g. "It is contrary to etiquette to yawn").  It treats "to" as an
infinitive marker (PART+aux) and the following noun as a VERB with `dep=xcomp`.
This produces entries like `etiquette` tagged VERB.

This cannot be reliably fixed with mechanical POS correction rules:
- `dep_=pobj` guard does **not** fire (the dep is `xcomp`, not `pobj`)
- `dep_=pobj` would also produce **false positives** on genuine infinitives that
  spaCy mis-parses as prepositional objects (e.g. "to yawn" → VERB+pobj)
- The same surface structure is grammatically ambiguous ("My job is to teach" =
  legitimate VERB+xcomp)

**Step 2B Claude review MUST catch and fix these.**  Check for NOUN entries
tagged as VERB whose head is a copula ("be") and where the preceding "to" is
not a true infinitive marker.  Correction: `pos → "NOUN"`, `definition_cn`
changed to noun format.

Symptom: common nouns like "etiquette" tagged VERB with `dep=xcomp, head=is`.
Check: `grep '"pos": "VERB"'` in match_sentences output for words that look
like nouns following "contrary to" / "subject to" / similar adjective+to patterns.

### spaCy dobj bare-infinitive mis-tag after semi-modals (NOT mechanically fixable)

spaCy mis-parses bare infinitives after semi-modal verbs (dare, need, help)
as direct objects.  In "What the little prince did not dare confess", "confess"
is tagged as NOUN with `dep=dobj` in complex cleft sentences, and as ADJ with
`dep=dobj` in simpler constructions.  The same word produces different POS tags
in different sentence structures, making a single mechanical rule impossible.

This cannot be reliably fixed with mechanical POS correction rules:
- `pos_=NOUN + tag_=VB` is impossible in the current spaCy 3.8.0 model
  (no morphologizer; `pos_` is deterministically derived from `tag_`)
- `lemminflect.getLemma()` returns the surface form for ALL words (including
  non-verbs like "apple") — it cannot serve as a verbness filter
- A head-based check (`token.head.lemma_ in ("dare", "help", "need")`)
  would work but requires a hard-coded word list, violating the "no hard-coded
  semantic word lists" design principle

**Step 2F Claude review MUST catch and fix these.**  Check for entries where
`dep=dobj` and the word follows a semi-modal taking bare infinitives
(dare, need, help).  In the sentence, verify whether the word functions
as a bare infinitive rather than a true direct object.
Correction: `pos → "VERB"`, `definition_cn` changed to verb format.

Symptom: verbs like "confess" tagged NOUN or ADJ with `dep=dobj` after dare.
Check: `grep '"dep": "dobj"'` in match_sentences output for NOUN/ADJ entries
whose head word is a semi-modal.

### Sentence-initial inverted ADJ detection ("Absurd as it might seem")

**Change (2026-07-08)**: `match_sentences.py` main loop now detects sentence-initial inverted adjective constructions. In "Absurd as it might seem" (= "As absurd as..."), spaCy tags "Absurd" as PROPN (capitalized at sentence start), then PROPN→NOUN converts to NOUN. The fix checks: `pos == "NOUN" AND token.i == 0 AND dep in ("advcl", "root", "ROOT") AND next_token == "as" AND lemminflect ADJ channel returns the surface form`.

Two guards prevent false positives:
1. `dep_ in ("advcl", "root", "ROOT")` — excludes npadvmod (noun phrases as adverbial modifiers). "King as he was" → dep=npadvmod → NOT converted.
2. `lemminflect.getLemma(token_lower, 'ADJ')[0] == token_lower` — confirms the word actually has a valid adjective form matching the surface token.

Symptom: "absurd" tagged NOUN in "Absurd as it might seem". Check: `grep '"pos": "NOUN"'` in match_sentences output for sentence-initial words followed by "as".

### cmudict -ly adverb IPA fallback (suffix stripping)

**Change (2026-07-08)**: `match_sentences.py`'s `_cmu_ipa()` now strips common derivational suffixes and retries the base form when the exact word is not in cmudict. Covers `-ly` (indulgently→indulgent+/li/), `-ness` (happiness→happy+/nəs/), `-ment`, `-tion`, `-sion`. Falls through gracefully when the base is also not in cmudict — Claude still provides IPA for those.

**Change (2026-07-10)**: Added `-ion` suffix (dejection→deject+/ʃən/) — ordered after `-tion`/`-sion` so more-specific matches take priority.  Added y→i spelling recovery for `-ly`: when stripping `-ly` leaves a stem ending in `i` that is not in cmudict, retries with `i`→`y` (thriftily→thrifti→thrifty+/li/).  Both only fire when the exact word is not in cmudict; all common words already have cmudict entries, so false-positive risk is near zero.

This reduces the number of words needing manual IPA from Claude. The fallback only works when the base form is in cmudict (e.g., "indulgent" is in cmudict → "indulgently" gets IPA automatically). Words with stem changes (e.g., "simply" → "simple" — stripping "ly" gives "simp" which is not in cmudict) still need Claude-provided IPA.

Symptom before fix: `indulgently` had empty IPA despite "indulgent" being in cmudict. Check: `grep '"ipa": ""'` in match_sentences output.

### Irregular past-tense finite-verb detection

**Change (2026-07-08)**: `validation.py`'s finite-verb check now has three tiers: (1) auxiliary/modal verbs, (2) regular -ed/-s endings, (3) common irregular past-tense forms (`_IRREGULAR_PAST_TENSE`: 59 words — made, went, told, found, etc.). Previously only tiers 1-2 existed, causing false-positive "may lack a finite verb" warnings for sentences like "I made the acquaintance..." where "made" is a past-tense main verb that matches neither an auxiliary list nor a regular -ed ending.

All three tiers are soft warnings — they print to stderr but never block sync.

Symptom before fix: `"And so I made the acquaintance of the little prince"` flagged as possibly lacking a finite verb.

### OCR punctuation correction in Step 2B

**Change (2026-07-08)**: Step 2B now requires Claude to check for and fix OCR punctuation errors at sentence endings. If a sentence ends with `:` or `,` but is grammatically complete (has subject+verb) and the following text is not a dialogue quote, the colon/comma is likely an OCR misread of a period. Claude replaces the final character with `.`.

Constraints: only sentence-final punctuation may be changed; never edit mid-sentence punctuation. This runs before DeepL translation (Step 2C), so translation is unaffected. `SHARED_WORKFLOW.md` Step 2B documents the full rules.

Symptom: sentences like `"I scribbled this drawing:"` in Internet Archive texts where the original has a period. Step 1 also now includes an OCR quality checklist to catch these early.

### char_offset substring matching (word-boundary fix)

**Change (2026-07-08)**: `match_sentences.py` `char_offset` computation previously used `str.find()` which performs substring matching — "ram" would match inside "grammar" (g-**ram**-mar), producing a wrong `char_offset` pointing to an unrelated part of the text. Replaced with `_first_word_boundary_offset()` which uses `\b` word-boundary regex (`re.search(r'\b' + re.escape(form) + r'\b', ...)`). Affects all short word forms that appear as substrings of longer words.

Symptom: `char_offset` for "ram" pointing to "grammar" instead of "This is a ram." Check: any entry where `char_offset` points to a word that doesn't match the sentence.

### Source text HTML wrapper detection

**Change (2026-07-08)**: Step 1 (SKILL.md) and Step 2A-a/b (SHARED_WORKFLOW.md) quality verification now include a plain-text format check: `head -c 100 <file> | grep -q '<html\|<!DOCTYPE'` → reject and re-fetch. Cache filename validation in SHARED_WORKFLOW.md Step 2A-0: cached files must match `*-<8位hex>-full.txt` format (uuid8 = `[0-9a-f]{8}`); old-format files (e.g. `tlp-full.txt`) trigger a cache miss and re-download. Internet Archive: must use `/download/` path (raw file), not `/stream/` (HTML viewer); URL format: `https://archive.org/download/<id>/<filename>_djvu.txt`.

**Change (2026-07-08)**: Added mechanical defence: `validate_plain_text()` in `lib/utils.py` scans first 500 chars for HTML signatures (`<!doctype html>`, `<html>`, `<head>`, `<body>`, `<meta>`, `<title>`) and calls `sys.exit(1)` when detected. Called in `match_sentences.py` after reading source text, and in `filter_fulltext.py` after reading stdin. Previously detection was purely procedural (Claude shell commands) — an HTML file could be silently processed if the manual check was skipped.

Symptom: 237KB cached file instead of expected 94KB; `head -c 500` shows HTML tags. Check: `file /tmp/*-full.txt` or `head -c 100` for `<!DOCTYPE`/`<html`.

### Cross-chapter sentence matching without --end-offset

**Change (2026-07-08)**: Added `--end-offset` parameter to `match_sentences.py`. When extracting vocabulary for a single chapter, passing the full book text as `source_text` with `--start-offset` alone would search from that offset to EOF, allowing words to be matched to sentences from later chapters (e.g. "grief" in Chapter 4 matched to Chapter 8's sentence). Use `--start-offset` + `--end-offset` to limit the search range, or extract the chapter to a separate file and pass that as `source_text`.

Symptom: word appears in Chapter 4 but its sentence comes from Chapter 8 or 21. Check: compare `char_offset` against known chapter boundary offsets. Fix: add `--end-offset <chapter_end>` to the match_sentences.py command, or use the chapter-extracted file as source_text.

### extract_chapter.py --chapter field matching with --boundaries-file

**Change (2026-07-08)**: When `--boundaries-file` is used, `--chapter N` now searches for a boundary entry whose `chapter` field equals N, rather than using `N-1` as an array index. Previously a single-entry boundaries file `[{"chapter": 4, ...}]` with `--chapter 4` would fail (`idx=3 >= len=1`). `--list` output also changed: shows `ch4:` instead of array position `1:` when using boundaries-file.

Symptom: `--chapter 4 --boundaries-file` exits with "chapter 4 not found" even though the file contains `"chapter": 4`. Workaround was `--chapter 1`.

### Chapter extraction for books without headings (--boundaries-file)

**Change (2026-07-08)**: `extract_chapter.py` now supports `--boundaries-file` for books without explicit chapter headings (e.g. Katherine Woods translation of The Little Prince). Claude identifies chapter boundaries semantically, writes a JSON file `[{"chapter": 1, "start": 0, "end": 6974}, ...]`, and passes it via `--boundaries-file`. When provided, `find_chapter_boundaries()` is skipped.

Symptom: `extract_chapter.py --list` prints "No chapter headings detected" despite the book clearly having chapters.

### "be + VBN + by" emotional -ed adjectives misclassified as VERB

spaCy analyses past participles in "be + VBN + by" constructions as verbal passives. For emotional/stative adjectives like "disheartened" ("I had been disheartened by the failure"), this produces `pos="VERB"`, `lemma="dishearten"` — the lemma is reduced to a base verb that does not appear in the text.

This is an inherent limitation of mechanical POS analysis — distinguishing "disheartened by" (emotional state, → ADJ) from "broken by" (action on patient, → VERB) requires semantic understanding.

**Fix workflow**:
1. **Step 2F (Claude review)** — detects "be + VBN + by" constructions where the VBN may be an emotional/stative adjective. Test: "very + word" (e.g. "very disheartened" ✓ → ADJ; "very broken" on a window ✗ → VERB). When confirmed, corrects `pos` → `"ADJ"` and `lemma` → surface form in the JSON.
2. **Do NOT fix this with hard-coded adjective sets in Python.**


Symptom: `lemma` is a verb base not appearing in the text (e.g. "dishearten" for "disheartened"). Check: entries where `lemma != word` and `word` ends in `-ed` following a be-form.

### VBD/VBN + advcl + no verbal dependents → ADJ (depictive predicate adjectives)

**Change (2026-07-10)**: Added mechanical detection of depictive predicate adjectives.
A lone past participle (`tag_` in `VBD`, `VBN`) in `dep=advcl` position with
no children other than punctuation is a depictive predicate adjective, not a
true adverbial clause.  E.g. "went away, **puzzled**." — "very puzzled" test
confirms ADJ.

The rule is gated by three conditions to prevent false positives:
1. `tag_ in ("VBD", "VBN")` — only past participles; present participles
   (`VBG`, e.g. "smiling") are excluded because they are more often genuinely
   verbal
2. No verbal dependents — genuine adverbial clauses have structure (subjects,
   objects); a lone participle is adjectival
3. `dep_ == "advcl"` — other dependency relations (`acl`, `ROOT`) are not
   affected

The *lemma* is also set to the surface form (`token_lower`) to prevent
lemmatizer reduction (e.g. "puzzled" stays "puzzled" not "puzzle").

Symptom: "puzzled" / "exhausted" tagged VERB+advcl instead of ADJ.
Check: `grep '"dep": "advcl"'` in match_sentences output for VBD/VBN entries
that pass the "very + word" test.

### smart_truncate() — automated sentence truncation (Step 2B pre-pass)

**Change (2026-07-09)**: `smart_truncate()` added to `match_sentences.py` as a mechanical pre-pass before Step 2B Claude review.  Truncates sentences >250 chars from the END only (preserving `target_offset`).  Scans backwards for sentence-ending punctuation (`.!?`), handles unclosed double quotes by walking back to the opening quote, and avoids ending on function words.

**Change (2026-07-10)**: Phase 1 now accepts `. ! ?` followed by space + capital letter as a sentence boundary even when inside an unclosed quote — this handles multi-quote dialogue where the scan range doesn't reach the closing quote.  A new `_cleanup_unclosed_quote()` helper removes unbalanced opening quotes and preceding text from truncated results, preserving the target word.

Run after `match_sentences.py` (Step 2A), before Step 2B Claude review:

```python
from lib.scripts.match_sentences import smart_truncate
new_sent, new_to, was_trunc = smart_truncate(sentence, word, target_offset)
# was_trunc=False + len(sentence) > 250 → needs manual review
```

`SENTENCE_END_FUNCTION_WORDS` in `lib/config.py` is the shared set of function words
used by both `smart_truncate()` and `validate_word_entries()`.

### _merge_adjacent_fragments() — automatic PySBD fragment merging

**Change (2026-07-09)**: `split_sentences()` now automatically merges adjacent fragments
split by blank lines in the source text.  `_merge_adjacent_fragments()` checks if
sentence N is a fragment (via `_is_fragment()`) AND sentence N+1 starts with lowercase,
then verifies the merged candidate is a continuous substring of the source text using
`build_sentence_regex()`.  Merges are applied repeatedly until stable.

This catches artifacts like `"which was at"` + `"the same time both simple and majestic."`
→ `"which was at the same time both simple and majestic."`

Integrated into `split_sentences()` — pass `source_text` parameter to enable:
```python
sentences = split_sentences(text, source_text=text)
```

Symptom before fix: sentences like "Clad in royal purple... which was at" ending with
function word "at"; "the same time both simple and majestic." starting lowercase.
Check: `grep '"is_fragment": true'` in match_sentences output for fragments that
should have been merged.

### check_step_completed.py new options (2B-verify, 2E, 2F-dup)

**Change (2026-07-09)**: Three new `--step` options added:

| Option | Purpose | When to run |
|--------|---------|-------------|
| `--step 2B-verify` | Verify `target_offset` points to correct word | After Step 2B truncation |
| `--step 2E` | Check all words have `definition_cn` + `ipa` | After Step 2E content generation |
| `--step 2F-dup` | Detect `(lemma, pos)` duplicates from POS fixes | After Step 2F, before Step 2G |

`--step 2E` is equivalent to `--step 2F` for field completeness (same checks).

### Lowercase sentence starts now HARD ERROR in validation

**Change (2026-07-09)**: `validate_word_entries()` now treats sentences starting with
a lowercase letter as a **hard error** (was soft warning).  A lowercase start is a
reliable signal that the sentence is a truncated fragment (the first half was cut off
by PySBD at a blank line).  This blocks sync and forces Claude to fix the fragment
in Step 2B.

Symptom: sync blocked with "sentence starts with lowercase 'a' — likely a truncated
fragment".  Fix: extend the fragment backward in the source text to find the complete
sentence, or use `_merge_adjacent_fragments()` to prevent the issue at the source.

### Step 2F POS fix dedup — sync_anki.py now prints dropped entries

**Change (2026-07-09)**: `sync_anki.py` deduplication now prints details of each
dropped `(lemma, pos)` entry to stderr.  This makes Step 2F POS fix collisions
visible — previously the drops were silent.

Also run `check_step_completed.py --step 2F-dup` before sync to detect duplicates
and give Claude a chance to fix them.

### Step 2E batch processing pattern documented

**Change (2026-07-09)**: `lib/SHARED_WORKFLOW.md` Step 2E now includes complete
commands for splitting JSON into ≤25-word chunks, launching parallel agents,
and merging results.  See `lib/SHARED_WORKFLOW.md` Step 2E for the documented
pattern.

### smart_truncate no longer forces word-boundary truncation

**Change (2026-07-09)**: `smart_truncate()` step 3d (word-boundary fallback) has been
removed.  When no sentence-ending punctuation (`.!?`) is found within `max_len` chars,
the function now returns the original sentence unchanged with `was_truncated=False`.
Entries with `len(sentence) > 250` are then flagged `_needs_manual` for Step 2B
Claude review.

Previously, smart_truncate would truncate at the last word boundary before `max_len`,
producing fragments like `"…and started"` without terminal punctuation.  A missing
period is a cosmetic issue, but truncating mid-clause at an arbitrary word boundary
produces unreadable sentences — worse than leaving the entry for manual review.

Symptom: `was_truncated=False` for sentences >250 chars with no internal `.`, `!`, or `?`.
Check: `grep '"sentence":' | awk 'length($0) > 250'` after Step 2B-0.

### Non-body-text auto-exclusion (`_is_non_body_text`)

**Change (2026-07-09)**: `process_words()` in `match_sentences.py` now automatically
skips entries whose matched sentence comes from non-body-text sections.  Detection
is purely mechanical — no hard-coded word lists:

| Pattern | Example |
|---------|---------|
| ALL CAPS title list (≥25 chars) | `"THE OLD MAN AND THE SEA ACROSS THE RIVER…"` |
| Copyright / legal boilerplate | `"IF THE BOOK IS UNDER COPYRIGHT…"` |
| Producer / transcriber credit | `"Produced by Al Haines"` |
| Dedication (≤6 words) | `"TO MAX PERKINS"` |
| End-of-text marker | `"[End of The Old Man and the Sea…]"` |

Previously, COCA-valid words from bibliography, copyright, and dedication sections
were matched to non-body-text sentences and had to be manually excluded in Step 2B.

Symptom: bibliography titles or copyright lines appearing as sentence text.
Check: entries with `sentence` starting with ALL CAPS or boilerplate phrases.

### Step 2B fragment repair: never use `\n` as sentence boundary

**Change (2026-07-09)**: `lib/SHARED_WORKFLOW.md` Step 2B fragment repair workflow now
explicitly documents correct sentence-boundary detection.  When walking backward in
the source text to find the true sentence start, ONLY treat `. ! ?` followed by
space + uppercase letter as a boundary — never `\n`.

Using `\n` as a boundary (e.g., `while start > 0 and source_text[start-1] not in
'.!?\\n'`) causes paragraph-internal newlines (e.g., `"huge,\\nstupid"`) to be
treated as sentence starts, creating lowercase-start fragments like
`"stupid loggerheads…"`.

Symptom: sentence text starts with lowercase letter.  Check: `grep '"sentence": "[a-z]'`.

### Step 2E JSON format: ASCII quotes only, pre-merge validation

**Change (2026-07-09)**: Step 2E agents MUST use Python's `json.dump(data, f,
ensure_ascii=False, indent=2)` to write chunk files.  All JSON keys and string
values must use ASCII straight quotes (`"` U+0022) — curly/smart quotes
(`"` `"` `'` `'`) break `json.load()`.  A pre-merge validation step
(`for f in chunks/*.json; do python3 -c "import json; json.load(open('$f'))"`)
has been added to the merge workflow.

`check_step_completed.py --step 2E-verify` scans the merged output for curly
quotes in all string fields.

Symptom: `json.JSONDecodeError` when merging chunks.  Check: run
`check_step_completed.py --step 2E-verify` on the merged JSON.

### filter_pipeline.py Anki dedup never matches (lemma extraction bug)

`query_anki_existing()` extracts `{lemma}_{pos}` from WordId via `rsplit("_", 1)[0]`
(e.g. `"abode_NOUN"`).  `_lemma_handled()` compares bare lemma (`"abode"`) against
this set — `"abode" not in {"abode_noun"}` is always True, so the Anki dedup
silently fails, showing "0 in Anki" even with hundreds of existing cards.

**Fix (2026-07-09)**: `query_anki_existing()` now also adds the bare lemma
(extracted from `{lemma}_{pos}` via `.split("_", 1)[0]`) to the same set.
This enables `_lemma_handled`'s lemma-level check to succeed.  Exact
`{lemma}_{pos}` dedup is still performed by `sync_anki.py` at sync time.

Symptom: filter pipeline shows "0 in Anki" when cards already exist.
Check: query Anki directly `curl ... findNotes WordId:*_{bookId}` and
compare count against filter output.

Same fix applied to `ankiconnect.py:query_anki_all_lemmas()`.

### sync_anki.py deck resolution: highlight cards landing in graded subdeck

`find_deck_for_book_id()` returned the first card's full deck path (e.g.
`"X - 分级词汇::X - 分级词汇 - COCA 4"`), and `sync_anki.py` blindly
overrode the derived deck name with it.  This caused highlight-mode cards
to land in vocab-book's graded subdecks.

**Fix (2026-07-09)**: Deck resolution moved from `find_deck_for_book_id()`
(which now returns raw deck names) into `sync_anki.py` caller with mode-aware logic:
- Subdeck hierarchy (`::COCA 4`) → extract top-level parent
- Highlight mode (`book_id` present, no `suffix`) → strip ` - 分级词汇` suffix
- Vocab-book mode (`suffix` present) → keep graded suffix
- Only override when resolved name differs from `_derive_deck_name()`

Symptom: highlight-mode Anki cards appear in `... - 分级词汇::... - COCA 5-20`
instead of the main deck `{title} ({author})`.

### char_offset drift from normalization that removes characters

`_sentence_char_offset()` computed `char_offset = match_start + target_offset`.
But `target_offset` is measured in the fully-normalized sentence (after
`_normalize_dialogue_attribution` joins `\\n\\n` → ` ` and
`_merge_adjacent_fragments` concatenates fragments), while `match_start`
is in text that only went through `_normalize_quotes`.  When normalization
removed characters before the target word, the offset was wrong.

**Fix (2026-07-09)**: `_sentence_char_offset()` now accepts an optional
`forms` parameter and uses word-boundary regex search from the match
position instead of `target_offset` arithmetic.  The caller passes
`all_forms` to enable this.

Symptom: `source[char_offset:char_offset+len(word)]` returns wrong text
(e.g. `"ry tedi"` instead of `"tedious"`).  Step 2B truncation from source
text fails.

### Step 2E POS abbreviations: agents used Chinese inconsistently

`SHARED_WORKFLOW.md` Step 2E field description said `格式 [词性] 释义`
which agents interpreted differently — some used `[名]`/`[动]` (Chinese),
others `[n.]`/`[v.]` (English).  `check_step_completed.py` only accepts
English abbreviations.

**Fix (2026-07-09)**: Field description now specifies English-only
abbreviations with an explicit mapping: NOUN→`[n.]`, VERB→`[v.]`,
ADJ→`[adj.]`, ADV→`[adv.]`, ADP→`[prep.]`, PROPN→`[n.]`.

## Testing

- **Every bug fix must include a unit test** that reproduces the failure before the fix is applied.
- **Shared tests** live in `lib/tests/` (pytest, 307+ tests) — covers coca, lemmatize, utils, sync_anki, validation, auto_band, match_sentences, extract_chapter.
- **Skill-specific tests**: `vocab-anki/tests/` (filter_pipeline, 14 tests), `vocab-book/tests/` (filter_fulltext, 12 tests).
- **LLM output quality issues** are tested via `test_validation.py` — the validator catches intentional bad data, not LLM output.
- **Python code bugs** are tested directly with parametrized input/output assertions.
- Run all tests before committing:
  ```bash
  cd lib && /home/agent/.claude/skills/vocab-anki/.venv/bin/python -m pytest tests/ -v && \
  cd ../vocab-anki && .venv/bin/python -m pytest tests/ -v && \
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
