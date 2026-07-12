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
- **Source-truth-only sentences**: Book sentences come from mechanically matched source text (Step 2A). No fabricated or dictionary sentences. Source text unavailable → skip the batch. Sentence selection is also mechanical: `match_sentences.py` scans sentences once (not per-word), does per-sentence spaCy POS analysis, and incrementally updates the best candidate per (lemma,pos) via `_better()` (three-tier XOR comparison: sweet-spot 30-500 > long > very-short). No candidates accumulation.
- **Source-truth-only translations**: Translations must be of the mechanically matched sentence. Never substitute a translation from memory even if you recognize the passage — this causes sentence/translation mismatch.
- **Incremental safety**: sync mode only adds, never modifies existing cards.
- **Graceful degradation**: audio failures don't block card generation.
- **Filter-first**: all mechanical filtering happens BEFORE Claude generates content.
- **Per-sentence POS-gated lemmatization**: `match_sentences.py` runs spaCy on each selected sentence to determine POS and lemma. Multi-signal adjective detection (POS=ADJ, adjectival dep, VBG+amod, be-to pattern, spacy_lemma==word, PROPN guard, -ly adverb guard). Falls through to lemminflect with the correct POS channel. No global voting — POS is determined from the specific sentence context. Claude does NOT set lemma (it is mechanically authoritative).
- **Truncate before translate**: sentence truncation (≤500 chars) must complete before DeepL/Claude translation. Never translate then truncate — causes sentence/translation mismatch.
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

**Step 2B pre-pass**: Run `smart_truncate()` mechanically to shorten sentences
exceeding `MAX_SENTENCE_LENGTH` by scanning for `.`, `!`, `?` boundaries in two
directions from the target word.  Sentences that cannot be shortened are kept
as-is — no manual truncation needed.  See `lib/SHARED_WORKFLOW.md` Step 2B.

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

**Fix (2026-07-08)**: `match_sentences.py` now marks fragment candidates with `is_fragment=True` (via `_is_fragment()` — detects missing sentence-ending punctuation, unclosed quotes, lowercase starts). `_better()` Tier 0 deprioritizes fragments: a complete sentence always beats a fragment; if the only candidate is a fragment, it still wins (to avoid data loss). `check_step_completed.py --step 2B` flags sentences lacking terminating `. ! ?`. **(Superseded 2026-07-11: Step 2B now rejects fragments instead of repairing them.)**

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

### spaCy dobj bare-infinitive mis-tag after perception verbs (NOT mechanically fixable)

The same `dep=dobj` bare-infinitive mis-tag also occurs after perception verbs
(see, hear, watch, feel, notice, observe).  In "I could see the sunlight shimmer",
"shimmer" is tagged as NOUN with `dep=dobj` — it is actually a bare infinitive
complement of "see".

This shares the same root cause as the semi-modal case above (dare, need, help):
spaCy mis-parses the bare infinitive as a direct object.  A mechanical fix would
require a hard-coded perception-verb list, violating the "no hard-coded semantic
word lists" design principle.

**Step 2F Claude review MUST catch and fix these.**  Check for entries where
`dep=dobj` and `pos` is NOUN or ADJ, and the head word is a perception verb
(see, hear, watch, feel, notice, observe).  Verify the word functions as a
bare infinitive in the sentence.
Correction: `pos → "VERB"`, `definition_cn` changed to verb format.

Symptom: verbs like "shimmer" tagged NOUN with `dep=dobj` after see/hear/watch.
Check: `grep '"dep": "dobj"'` in match_sentences output for NOUN/ADJ entries
whose head word is a perception verb.

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

### Irregular past-tense finite-verb detection (REMOVED 2026-07-11)

**Change (2026-07-08)**: `validation.py`'s finite-verb check now has three tiers: (1) auxiliary/modal verbs, (2) regular -ed/-s endings, (3) common irregular past-tense forms (`_IRREGULAR_PAST_TENSE`: 59 words — made, went, told, found, etc.). Previously only tiers 1-2 existed, causing false-positive "may lack a finite verb" warnings for sentences like "I made the acquaintance..." where "made" is a past-tense main verb that matches neither an auxiliary list nor a regular -ed ending.

All three tiers are soft warnings — they print to stderr but never block sync.

Symptom before fix: `"And so I made the acquaintance of the little prince"` flagged as possibly lacking a finite verb.

**Removed (2026-07-11)**: The entire three-tier finite-verb detection and the `_IRREGULAR_PAST_TENSE` hard-coded set (65 words) were removed from `validation.py`.  The check was inherently unreliable — English has 200+ irregular verbs, the set can never be complete — and violated the "no hard-coded semantic word lists in Python" design principle.  Its only production trigger was a false positive on "cast" in "But it cast an enchantment over that house."  True sentence fragments are already caught by `is_fragment=True`, lowercase-start hard error, and function-word-ending hard error.  See also [[MAX_SENTENCE_LENGTH vs HARD_CUTOFF]].

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
no *verbal* children (subjects, objects, agents) is a depictive predicate
adjective, not a true adverbial clause.  E.g. "went away, **puzzled**." or
"**Clad** in royal purple, he was seated..." — "very puzzled" / "very clad"
test confirms ADJ.

The rule is gated by three conditions to prevent false positives:
1. `tag_ in ("VBD", "VBN")` — only past participles; present participles
   (`VBG`, e.g. "smiling") are excluded because they are more often genuinely
   verbal
2. No verbal dependents — children in `_VERBAL_DEPS` (nsubj, dobj, iobj,
   xcomp, ccomp, aux, auxpass, agent, nsubjpass, expl, pobj) indicate a
   genuine clause.  Prepositional-phrase modifiers (prep), conjunctions (cc),
   and adverbial modifiers (advmod) are NOT verbal arguments — a VBN with
   only these is adjectival.
3. `dep_ == "advcl"` — other dependency relations (`acl`, `ROOT`) are not
   affected

The *lemma* is also set to the surface form (`token_lower`) to prevent
lemmatizer reduction (e.g. "puzzled" stays "puzzled" not "puzzle").

**Change (2026-07-11)**: Fixed the `verbal_children` check to use `_VERBAL_DEPS`
(shared with the advmod rule) instead of `c.dep_ not in ("punct",)`.  The old
check treated ANY non-punctuation child — including prepositional-phrase
modifiers — as evidence of a verbal clause.  This caused false negatives for
participles with prepositional modifiers (e.g. "Clad in royal purple" — "in"
is prep, not a verbal argument).  Now only children in `_VERBAL_DEPS` block
the ADJ promotion.

Symptom: "clad" / "dressed" / "covered" + prepositional phrase tagged
VERB+advcl instead of ADJ.
Check: `grep '"dep": "advcl"'` in match_sentences output for VBD/VBN entries
with prepositional modifiers that pass the "very + word" test.

### VBN + preceding ADV advmod → ADJ (adjectival participle detection)

**Change (2026-07-10)**: The VBN+advmod→ADJ rule now requires three conditions:
1. `child.dep_ == "advmod"` — the child must have advmod dependency
2. `child.pos_ == "ADV"` — the child must be a true adverb (excludes SCONJ
   subordinators like "When" and ADP particles like "along")
3. `child.i < token.i` — the adverb must precede the participle (excludes
   postposed phrasal-verb particles like "trudged **along**", "went **away**")

Before this change, the rule had no POS or position gates, causing false
positives when phrasal-verb particles (tagged as advmod) or subordinating
conjunctions (also advmod) were children of a VBN token.

Symptom: "trudged" in "had trudged along" tagged ADJ instead of VERB.
Check: `grep '"pos": "ADJ"'` in match_sentences output for VBN words
with postposed particles or SCONJ advmod children.

### smart_truncate() — automated sentence truncation (Step 2B pre-pass)

**Change (2026-07-09)**: `smart_truncate()` added to `match_sentences.py` as a mechanical pre-pass before Step 2B Claude review.  Scans for sentence-ending punctuation (`.!?`) in two directions from the target word.  Sentences that cannot be shortened are kept as-is.

**Change (2026-07-10)**: Rewritten from max_len-window scan to two-direction scan: right (end-truncation at first `.`, `!`, `?` after target) and left (beginning-truncation at nearest `.`, `!`, `?` + capital before target).  `MAX_SENTENCE_LENGTH` raised from 250 to 500.  Manual truncation (`_needs_manual`) removed — sentences smart_truncate cannot shorten are accepted as-is.

**Change (2026-07-11)**: `smart_truncate()` integrated into `match_sentences.py` Step 5 post-processing — runs automatically after `_better()` sentence selection, per (lemma,pos) group.  Removed separate Step 2B-0 pre-pass from `SHARED_WORKFLOW.md`.  Step 2B now starts directly with Claude manual review.

**Change (2026-07-11)**: `smart_truncate()` Direction 1 no longer returns immediately when the truncation result > `MAX_SENTENCE_LENGTH`.  Instead, the result is fed into Direction 2 (left-side truncation), composing both directions.  Also added fallthrough: when both directions fail to reach `max_len`, Direction 1's best result is still returned (it IS shorter than the original).  `is_fragment` status is now recomputed **after** `smart_truncate` instead of inheriting from the pre-truncation `hard_truncate` result — prevents false fragments on properly truncated sentences.

**Change (2026-07-11)**: Step 2B fragment repair workflow removed.  Fragments that survive `_merge_adjacent_fragments()` are now **rejected** (word excluded from deck) instead of manually repaired.  Manual fragment repair is unreliable and the mechanical merging already handles most cases.

**Change (2026-07-11)**: Rule 2 (len ≤ `MIN_TRUNCATION_LENGTH` = 100 → return immediately) removed.  Complete short sentences are already caught by Rule 1's terminal-punctuation check (`.!?`).  Incomplete short sentences should fall through to Direction 1/2 for boundary scanning rather than being silently accepted.  `MIN_TRUNCATION_LENGTH` constant deleted from `lib/config.py`.

**Change (2026-07-11)**: `MAX_SENTENCE_LENGTH` lowered from 500 to 400.  `HARD_CUTOFF` remains at 500 as the upstream safety net.  Direction 1/2 scanning logic unchanged — the nearest sentence boundary is the best one.  If truncation produces a result > 400 chars, `validation.py` reports a hard error and Step 2B Claude rejects the word (sentence cannot be reasonably shortened).  See also [[MAX_SENTENCE_LENGTH vs HARD_CUTOFF]].

**Change (2026-07-11)**: `MAX_SENTENCE_LENGTH` lowered from 400 to 250.  400 chars (~6-8 lines on mobile) takes too long to read during spaced-repetition review.  250 chars (~4-5 lines, ~5 seconds) provides sufficient context for 2-3 clauses while keeping review efficient.  Complete sentences that cannot be mechanically truncated (no internal `. ! ?` boundaries) are now a soft warning, not a hard error — Step 2B has reviewed them and they cannot be shortened.  See also [[finite-verb check removed]].

**Change (2026-07-11)**: Finite-verb detection (three-tier: auxiliaries/modals → -ed/-s endings → `_IRREGULAR_PAST_TENSE`) and the `_IRREGULAR_PAST_TENSE` hard-coded set (65 words) removed from `validation.py`.  The check was inherently unreliable — English has 200+ irregular verbs, the set can never be complete — and violated the "no hard-coded semantic word lists in Python" design principle.  Its only production trigger was a false positive on "cast" in "But it cast an enchantment over that house."  True sentence fragments are already caught by `is_fragment=True`, lowercase-start hard error, and function-word-ending hard error.  See also [[MAX_SENTENCE_LENGTH vs HARD_CUTOFF]].

Run after `match_sentences.py` (Step 2A), before Step 2B Claude review:

```python
from lib.scripts.match_sentences import smart_truncate
new_sent, new_to, was_trunc = smart_truncate(sentence, word, target_offset)
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

### smart_truncate two-direction rewrite (2026-07-10, updated 2026-07-11)

**Change (2026-07-10)**: `smart_truncate()` rewritten from max_len-window scan to
two-direction scan from the target word.  Direction 1 scans right from
*target_end* for the first `.`, `!`, `?` that shortens the sentence.
Direction 2 scans left from *target_offset* for the nearest `.`, `!`, `?` +
capital boundary.  Both reuse existing quote-handling logic (dialogue
boundaries, opening-quote walk-back).  `MAX_SENTENCE_LENGTH` raised from
250 to 500.

**Change (2026-07-11)**: `MIN_TRUNCATION_LENGTH` (100 chars) removed.  Rule 2
(len ≤ 100 → return immediately) deleted — complete short sentences are
already caught by Rule 1's terminal-punctuation check (`.!?`).  Incomplete
short sentences fall through to Direction 1/2.  `MAX_SENTENCE_LENGTH`
lowered to 400 (see [[smart_truncate() — automated sentence truncation]]).

### VBD/VBN + dep=advmod → ADJ (depictive predicate adjective, 2026-07-11)

**Change (2026-07-11)**: Added mechanical detection of depictive predicate
adjectives in ``dep=advmod`` position (no comma).  A lone past participle
(``tag_`` in ``VBD``, ``VBN``) with ``dep=advmod`` and no verbal dependents
(subjects, objects, agents) is a depictive predicate adjective, not a true
adverbial modifier.  E.g. "stood there all **bewildered**."

The rule is gated by three conditions:
1. ``tag_ in ("VBD", "VBN")`` — only past participles; present participles
   (``VBG``, e.g. "running") are excluded because they are more often genuinely verbal
2. No verbal dependents — only children with ``_VERBAL_DEPS`` (nsubj, dobj,
   iobj, xcomp, ccomp, aux, auxpass, agent, nsubjpass, expl) count.
   Adverbial modifiers (advmod) and determiners (det) are not verbal arguments
3. ``dep_ == "advmod"`` — only the comma-less variant; the comma-separated
   variant (``dep=advcl``) was already covered

The *lemma* is also set to the surface form (``token_lower``) to prevent
lemmatizer reduction (e.g. "bewildered" stays "bewildered" not "bewilder").

Symptom: "bewildered" tagged VERB+advmod instead of ADJ.
Check: ``grep '"dep": "advmod"'`` in match_sentences output for VBD/VBN entries.

### sync_anki.py dedup uses _better() logic (2026-07-11)

**Change (2026-07-11)**: ``sync_anki.py`` main() deduplication changed from
first-wins to ``_better_sentence()`` comparison.  When two entries share the
same ``(lemma, pos)`` key, the entry with the better sentence is kept:
non-fragment beats fragment (Tier 0), shorter wins in sweet-spot (≥30 chars).
This is consistent with ``match_sentences.py``'s ``_better()`` sentence
selection logic.  ``MIN_SENTENCE_LENGTH`` (30) is imported from ``lib.config``.

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

### Preamble detection: bio continuation + literary-analysis intro lines

**Change (2026-07-11)**: ``detect_story_start()`` in ``lib/chapter_detect.py``
now skips two additional preamble patterns that were previously missed:

1. **Bio paragraph continuations**: When a ``_BIO_INDICATORS`` match occurs
   (e.g. "…who was a French author…"), subsequent lines in the same paragraph
   (not separated by a blank line) are treated as bio continuation.
   Previously the next line would hit ``_NARRATIVE_OK`` (starts with capital,
   ≥40 chars) and prematurely end preamble detection.
2. **Literary-analysis intro lines**: ``_META_INDICATORS`` catches lines that
   discuss the book as a literary work — ``appears to be``, ``is actually``,
   ``some would say``, ``profound and deeply moving``, ``written in riddles``,
   ``laced with (philosophy|poetic)``.  These patterns are highly specific to
   critical introductions and extremely unlikely in narrative prose.

Both are guarded by the existing ``len(line) < 200`` gate and only fire in the
fallback heuristic (no chapter headings).  ``_META_INDICATORS`` only scans the
first ~10 lines.

Symptom: words matched to critical-introduction sentences (e.g. "The Little
Prince appears to be a simple children's tale…") with ``char_offset`` in the
first ~400 chars of text.  Check: entries where the sentence reads like a
book review rather than narrative.

### Step 2B fragment repair: never use `\n` as sentence boundary (REMOVED 2026-07-11)

**Change (2026-07-09)**: `lib/SHARED_WORKFLOW.md` Step 2B fragment repair workflow now
explicitly documents correct sentence-boundary detection.  When walking backward in
the source text to find the true sentence start, ONLY treat `. ! ?` followed by
space + uppercase letter as a boundary — never `\n`.

Using `\n` as a boundary (e.g., `while start > 0 and source_text[start-1] not in
'.!?\\n'`) causes paragraph-internal newlines (e.g., `"huge,\\nstupid"`) to be
treated as sentence starts, creating lowercase-start fragments like
`"stupid loggerheads…"`.

Symptom: sentence text starts with lowercase letter.  Check: `grep '"sentence": "[a-z]'`.

**(Superseded 2026-07-11: Step 2B fragment repair workflow was removed entirely.
Fragments are now rejected — the word is excluded from the deck.)**

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

### sync_anki.py flat deck `existing` dict key = "" → dedup always skipped

**Change (2026-07-10)**: In flat deck mode (no COCA bands), the `existing`
dict was keyed by `""` (empty string) at L426 but looked up by `deck_name`
at L451-452, so ``existing.get(target_deck, {})`` always returned ``{}``.
The pre-add dedup was completely ineffective — all words passed through,
and AnkiConnect's own duplicate detection at ``addNotes`` time was the only
safeguard.  This also caused "Already in deck" to always print 0.

**Fix:** Changed L426 from ``existing = {"": ac.get_word_id_map(deck_name)}``
to ``existing = {deck_name: ac.get_word_id_map(deck_name)}``, consistent
with ``_get_existing_per_deck()`` behaviour in the bands code path.

Symptom: "Already in deck: 0" even when re-running with existing cards;
``addNotes`` batch call fails with duplicate error → slower individual retries.
Check: run with ``--dry-run`` on a deck with existing cards → "Already in deck"
should be non-zero.

### smart_truncate Direction 2 preserves opening quote of quoted speech

**Change (2026-07-10)**: When a quoted speech passage spans multiple
sentences inside one set of ``""``, PySBD correctly preserves it as a single
sentence.  ``smart_truncate`` Direction 2 (beginning-truncation) truncates
from the left, but slices off the opening ``"`` along with the preceding
sentences.  ``_cleanup_unclosed_quote`` detects the odd quote count but its
last-quote-is-unclosed heuristic finds nothing after the final ``"`` →
returns unchanged.  The opening quote is silently lost.

**Fix:** After Direction 2 truncation + ``_cleanup_unclosed_quote``, if the
original sentence starts with ``"`` and the truncated result does not,
prefix ``"`` and increment ``target_offset`` by 1.

Symptom: sentence has closing quotes and dialogue attribution (``," xxx
said``) but does not start with ``"``.  Check: ``grep '," '`` in JSON
output for sentences not starting with ``"``.

### smart_truncate Direction 1 strips closing quote of truncated dialogue

**Change (2026-07-11)**: When ``smart_truncate`` Direction 1 (end-truncation)
truncates within a quoted dialogue exchange, the closing ``"`` of the last
utterance can be sliced off, leaving an unclosed opening ``"``:

```
..."Little glittering objects." "Bees?" "Oh, no.   ← closing " lost
```

``_cleanup_unclosed_quote`` previously only handled the case where the
*target word* is AFTER the last unclosed quote (stripping the quote + text
before it).  When the target word is BEFORE the last unclosed quote, the
function gave up (``new_tgt < 0`` → returns unchanged).

**Fix**: ``_cleanup_unclosed_quote`` now has a second branch: when the
target word is BEFORE the last unclosed ``"``, strip from that ``"`` to
the end of the sentence (the trailing incomplete dialogue fragment),
keeping only the clean text before it.

Symptom: sentence ends with ``"Word.`` (opening quote, text, period —
no closing quote) after auto-truncation.  Check: ``grep '"Oh, no.$'``
or odd quote count in sentences with ``_auto_truncated: true``.

### lemmatize() Nation homograph split blocks correct VERB reductions

**Change (2026-07-10)**: The Nation word-family cross-validation in
``lemmatize()`` (``lib/lemmatize.py`` Step 6) can incorrectly reject a
valid VERB-channel reduction when Nation stores the verb and the noun
forms of the same word under different headwords.  e.g.:

| Word | → Lemma | Nation headword (word) | Nation headword (lemma) | Result |
|------|---------|----------------------|------------------------|--------|
| ``loafing`` | ``loaf`` (verb: "to idle") | ``loafed`` (verb family) | ``loaf`` (noun: "bread") | **BLOCKED** ← wrong |
| ``deliberating`` | ``deliberate`` | ``deliberated`` | ``deliberate`` | **BLOCKED** ← wrong |

Standard verbs (``running→run``, ``walking→walk``) are NOT affected —
they share the same Nation headword.  Only homograph verbs whose base
form collides with an unrelated noun (loaf, saw, etc.) trigger this.

**Fix (2026-07-10)**: Three changes to Step 6:
1. Track which ``upos`` produced the reduction (new ``reduced_upos`` variable)
2. When reduced_upos==VERB, spaCy confirms the word is NOT a noun
   (``_is_noun=False``, reusing the existing Step 5 guard), AND both
   words are in COCA → trust lemminflect, skip Nation check.
3. All other channels (NOUN/ADJ/ADV) and words tagged as nouns by spaCy
   keep full Nation protection.

373 VERB reductions unblocked (all correct), 203 noun/adj reductions
still blocked (e.g. ``aeronautics→aeronautic``, ``formers→former``).

**Why this is safe**: lemminflect VERB channel only handles inflectional
morphology (-ing/-ed/-s), not derivational.  The triple guard
(VERB channel + spaCy non-noun + COCA both-ways) prevents false
positives.  ``sync_anki.py`` provides a final WordId-exact dedup
defense-in-depth.

Symptom: filter_pipeline output shows a word in ``IN_COCA`` that should
be in ``ANKI_SKIPPED`` (already in Anki).  Check: ``grep <lemma>`` in
Anki via ``findNotes WordId:*_<bookId>`` — if the card exists but
wasn't deduped, this bug may be the cause.

See also: [[filter_pipeline.py Anki dedup never matches (lemma extraction bug)]]

### find_notes_by_field query syntax — outer quotes break Anki field search

**Change (2026-07-10)**: ``AnkiConnect.find_notes_by_field()``
(``lib/ankiconnect.py``) wrapped the Anki search query in outer double
quotes: ``"WordId:*_22720170"``.  Anki's search parser interprets
double-quoted strings as full-text phrase searches, NOT field-specific
searches.  The correct syntax is unquoted: ``WordId:*_22720170``.

The same function's deck-scoped path had the same issue:
``deck:"Name" "WordId:*_id"`` → ``deck:"Name" WordId:*_id``.

Contrast with ``find_deck_for_book_id`` (same file, line 372) which
already used the correct unquoted syntax.

**Fix (2026-07-10)**: Removed outer double quotes from both paths.
``find_notes_by_field`` is only called from ``filter_pipeline.py``'s
``query_anki_existing()``, so the impact is limited to the Anki dedup
step of the filter pipeline.

Symptom: ``findNotes`` returns inconsistent results between runs
(e.g. 143 vs 145 notes found for the same query).  Check: inspect the
query string in ``find_notes_by_field`` — if it has outer ``"`` quotes,
this bug is present.

### query_anki_existing — triple silent error swallowing

**Change (2026-07-10)**: ``filter_pipeline.py``'s ``query_anki_existing()``
had three layers of ``except: return set()`` that silently converted any
AnkiConnect failure into an empty dedup set — all words passed through
as "new".  No stack trace, no way to diagnose the failure.

**Fix (2026-07-10)**:
1. ``except AnkiConnectError`` → prints WARNING (same behavior, still
   returns empty set as graceful degradation)
2. ``except Exception`` → prints ERROR + full ``traceback.print_exc()``
   (still returns empty set, but now leaves diagnostic evidence)
3. Added ``len(info) != len(note_ids)`` validation after ``notes_info``
   call — prints WARNING when counts mismatch (partial dedup)

Symptom: filter_pipeline reports "0 in Anki" when cards clearly exist,
or ``n_anki_cards`` count differs between identical runs.  Check stderr
for WARNING/ERROR lines from AnkiConnect.

### conj POS inheritance: cc chain-walking + AUX copula fallback

**Change (2026-07-11)**: The ``conj`` POS inheritance logic (lines 908-926)
had two gaps in chain-walking to the coordination root:

1. **cc skip**: The while loop only walked past ``dep=conj`` nodes.  When
   a conjunct's head is a coordinating conjunction (``cc``, e.g. "and"),
   the loop stopped at the CCONJ node whose POS is not in the content-word
   whitelist — inheritance silently failed.  The loop now also walks past
   ``dep=cc`` nodes.

2. **AUX copula fallback**: spaCy sometimes attaches conjuncts directly to
   the copula rather than the adjective complement ("was thin and gaunt" →
   "gaunt" has head="was"(AUX), not "thin"(ADJ)).  When the chain-walking
   lands on an AUX node AND no intermediate content-word ``conj`` nodes
   were walked past (``walked_past_content`` guard), check whether the AUX
   has an ``acomp``/``amod`` child with POS ADJ — the conjunct shares that
   role and should also be ADJ.

   The ``walked_past_content`` guard prevents false ADJ promotion when the
   chain goes through a VERB before reaching AUX (e.g. "butchered" →
   "begged"(VERB,conj) → "was"(AUX) — butchered is a genuine VERB, not a
   copula complement).

Symptom: "gaunt" tagged VERB in "was thin and gaunt".  Check: ``grep
'"lemma": "gaunt".*"pos": "VERB"'`` in match_sentences output.

### hyphenated compound token skip (dep=compound + adjacent "-")

**Change (2026-07-11)**: Tokens with ``dep=compound`` that are adjacent to
a hyphen character in the sentence text are now skipped.  These are
fragments of hyphenated compounds (e.g. "mast" in "mast-head") — not
independent word occurrences.  Skipping them prevents duplicate (lemma,pos)
entries where the same word gets both an ADJ+compound card (from the
compound fragment) and a NOUN card (from a standalone occurrence).

The filter checks the gap between the token and its head in the sentence
text.  If the gap starts or ends with ``-``, the token is skipped.

Only ``dep=compound`` is filtered, not ``dep=amod`` — true adjectives in
hyphenated compounds like "fair-minded" (``dep=amod``) are legitimate
adjective occurrences and still match.

Symptom: "mast" produces two cards (ADJ from "mast-head" + NOUN from "put
the mast down") instead of one.  Check: ``grep '"lemma": "mast"'`` in
match_sentences output for duplicate entries.

### sync_anki.py progress display used lemmatize_word instead of JSON lemma

**Change (2026-07-11)**: The prefetch progress display in ``sync_anki.py``
(``_prefetch_audio``) recomputed the lemma from the surface word using
``lemmatize_word(word)`` for the display label, independently of the
authoritative JSON ``lemma`` field.  When Step 2F corrected a lemma
(e.g. ``disheartened`` VERB→ADJ, lemma ``dishearten``→``disheartened``),
the progress line showed the old mechanical lemma in parentheses:
``disheartened (dishearten)`` — confusing and inconsistent with the
actual audio filename (``disheartened_ADJ_22720170_word.mp3``).

**Fix**: Changed ``lemma = lemmatize_word(word)`` to
``lemma = w.get("lemma", "").strip() or word``.  The progress display
now uses the authoritative JSON lemma (which may have been corrected
in Step 2F).  Removed unused ``lemmatize_word`` import.

This is a display-only bug — audio filenames, WordId, and card content
were always correct (they used the JSON ``lemma`` via
``_process_one_word``).  Only the progress label was wrong.

Symptom: prefetch progress shows ``word (old_lemma)`` where ``old_lemma``
contradicts the actual audio filename.  Check: compare progress label
against ``ls /tmp/vocab_audio_*/`` filenames.

## Testing

- **Every bug fix must include a unit test** that reproduces the failure before the fix is applied.
- **Shared tests** live in `lib/tests/` (pytest, 566 tests) — covers coca, lemmatize, utils, sync_anki, validation, auto_band, match_sentences, extract_chapter, ankiconnect.
- **Skill-specific tests**: `vocab-anki/tests/` (filter_pipeline, 33 tests), `vocab-book/tests/` (filter_fulltext, 12 tests).
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

### `_merge_adjacent_fragments` bidirectional merge (2026-07-12)

**Change**: `_merge_adjacent_fragments()` rewritten from iterative
while-changed forward-only merging to single-pass bidirectional merging.

- **Forward merge** (unchanged trigger): fragment + lowercase-next → merge.
  Added odd-quote relaxation: fragment with odd `"` count also attempts forward
  merge even when the next sentence starts uppercase.
- **Backward merge** (new): fragment + previous fragment in `merged` →
  merge backward via `merged[-1] + " " + s`.  Both must be fragments.
- **Single pass**: `while changed` loop removed — no cascading.
- **Verification**: `build_sentence_regex()` against source text.

Symptom: fragments survive `_merge_adjacent_fragments` and get rejected in
Step 2B.  Check `grep '"is_fragment": true'` in match_sentences output.

### `_cleanup_unclosed_quote` forward search for closing quote (2026-07-12)

**Change**: `_cleanup_unclosed_quote()` accepts optional `tail` parameter
(the untruncated text after the truncation point).  When stripping before
the unclosed `"` would produce a lowercase-start sentence, searches `tail`
forward for the missing closing `"`.  If found, extends the result to include
it — correctness prioritised over `MAX_SENTENCE_LENGTH`.  Falls back to
original stripping when no `tail` or no closing `"` found.

Symptom: `smart_truncate` produces lowercase-start sentences from dialogue
where the closing `"` was truncated.

### `_cleanup_unclosed_quote` before_last_quote produces comma-ending fragment (2026-07-12)

**Change**: When `smart_truncate` Direction 1 truncates at `.` inside an
opening quote (with dialogue boundary `.` + space + capital), the result has
an unclosed `"`.  The "target word BEFORE unclosed quote" branch strips the
quoted speech, but the remaining text may end with `,` — a fragment.

**Example**: `'He was sorry for the birds, and he thought, "The birds have a harder life.'`
→ stripping from `"` onward leaves `'He was sorry for the birds, and he thought,'`
— ends with comma, no terminal punctuation.

**Fix**: Added fragment guard in the `before_last_quote` branch: if the stripped
result has no terminal punctuation (`.!?`), reject the strip and return the
original `result` unchanged.  `smart_truncate` then falls through to try other
truncation points or return the original sentence.

Symptom: sentence ends with `,` or other non-terminal punctuation after
auto-truncation.  Check: `grep '_auto_truncated.*true'` for entries whose
sentence ends with `,`.

### `smart_truncate` returns unclosed-quote fragments with `len <= max_len` (2026-07-12)

**Change**: `_cleanup_unclosed_quote`'s fragment guard correctly prevents
stripping quoted speech that would produce a comma-ending fragment.  But
the original (un-stripped) result still has an unclosed `"` (odd quote count)
and may be within `max_len`.  `smart_truncate` previously returned it
immediately, producing a fragment.

**Fix**: Added `not _is_fragment(result)` checks at all return sites in
`smart_truncate` where `_cleanup_unclosed_quote` results are returned.
Also added the check to the `d1_sentence` fallback at the end of the function.

Symptom: `is_fragment=True` and `_auto_truncated=True` on entries where the
sentence has an odd number of `"` characters.  Check: `grep '"is_fragment": true'`
with odd `"` count.

### `smart_truncate` fallback returns overwritten `d1_sentence` instead of original (2026-07-12)

**Change**: Direction 1 saves its best result in `d1_sentence`, then
overwrites the local `sentence` variable with it (line 454-455) for Direction 2.
When both Direction 1 and Direction 2 fail, the function fell through to
`return sentence, target_offset, False` — but `sentence` had been overwritten
with the (possibly fragment) `d1_sentence`, not the original.

**Fix**: Save `_orig_sentence` and `_orig_tgt` BEFORE the mutation at lines
454-455, and use them in the fallback `return` when `d1_sentence` is a fragment
or `None`.

Symptom: sentence is shorter than the original but `_auto_truncated` is `None`
(was_truncated=False), and `is_fragment=True`.  The sentence was reduced to
`d1_sentence`'s length even though truncation was "rejected."

### `_sentence_char_offset` form search scoped to sentence extent (2026-07-12)

**Change**: `_sentence_char_offset()` searched for word forms in
`text[match_start:]` — the entire remaining source text after the sentence
match.  When `all_forms` contained multiple surface forms (e.g. `["sardine",
"sardines"]`) and the matched sentence only contained the second form, the
first form's regex (`\bsardine\b`) would match in a **later** sentence,
returning the wrong `char_offset`.

**Example**: The matched sentence at offset ~10936 contained "sardines"
(plural), but `\bsardine\b` matched "sardine" (singular) at offset 24712 in
a different sentence ("Each sardine was hooked…").  `char_offset` was 24712
instead of the correct 10954.

**Fix**: The form search now uses `text[match_start : start + m.end()]`
(the regex match extent) as the primary search window.  A fallback to the
full `text[match_start:]` search handles edge cases where the flexible
regex matched a slightly different extent.

Symptom: `text[char_offset:char_offset+len(word)]` returns a different form
of the word than what appears in the sentence.  Check: compare the extracted
word at `char_offset` against the `word` field and verify it's in the
sentence text.

### Walk-back + `_cleanup_unclosed_quote` accept dialogue-attribution comma (2026-07-12)

**Change**: When `smart_truncate` walks back to before an opening `"`, the
text before the quote often ends with a dialogue-attribution comma:
`…and he thought, "The birds…"`.  Both the walk-back logic and
`_cleanup_unclosed_quote` previously rejected comma-ending text as a
potential fragment, even though the clause is grammatically complete.

**Fix**: Three changes work together:

1. **`_walk_back_pre_quote_ok()`** — new helper that accepts `pre_quote`
   ending with `,` when the comma is immediately before `"` in the
   sentence (dialogue-attribution pattern).
2. **`_strip_dialogue_attribution_comma()`** — new helper that replaces the
   trailing `,` with `.` — the clause before a dialogue quote is
   grammatically complete and needs terminal punctuation when the quoted
   speech is removed.
3. **`_cleanup_unclosed_quote`** — the "target word BEFORE unclosed quote"
   branch now detects comma-ending `before_last_quote` and replaces `,` with
   `.` instead of rejecting it.

**Example**: The tern sentence from *The Old Man and the Sea* — a 496-char
hard-truncated dialogue passage.  The walk-back produced `"He was sorry for
the birds, …and he thought,"` (146 chars, comma-ending).  Before the fix
this was rejected as a fragment and "tern" was excluded from the deck.
After the fix, the comma is replaced with a period: `"…and he thought."` —
a valid, complete 146-char sentence.

Symptom: `is_fragment=True` on sentences where the target word is in the
narrative part before a long quoted dialogue passage, and the sentence
exceeds `MAX_SENTENCE_LENGTH`.  Check: `grep '"is_fragment": true'` for
entries whose sentence contains `,"` (comma-quote dialogue attribution).

## License

Apache License 2.0 — all contributions are under this license.
