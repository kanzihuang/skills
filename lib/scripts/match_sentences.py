#!/usr/bin/env python3
"""Step 2A: Mechanical sentence matching + POS-aware lemmatization.

Reads filter_fulltext.py JSON output and source text, splits text into
sentences once, and makes a single pass: each sentence is run through
spaCy once; matched entries update their (lemma, pos) best sentence
incrementally.  No candidate accumulation — only the best entry per
(lemma, pos) group is retained.

Output sentences are stored WITHOUT <b> tags — sync_anki.py adds <b> tags
when building Anki cards.

No semantic truncation — that is handled by Step 2B (Claude).  Only a hard
500-char cutoff guards against extreme outliers.
"""

import json
import os
import re
import sys

import pysbd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.chapter_detect import detect_story_start
from lib.config import HARD_CUTOFF, MIN_SENTENCE_LENGTH, MAX_SENTENCE_LENGTH


def _get_segmenter() -> pysbd.Segmenter:
    """Return a cached PySBD segmenter (lazy init)."""
    return pysbd.Segmenter(language="en", clean=True)


_DIALOGUE_ATTRIBUTION_RE = re.compile(r'([:,])[ \t]*\n[ \t]*\n[ \t]*"')


def _normalize_dialogue_attribution(text: str) -> str:
    """Join colon/comma-ending attribution lines with their dialogue.

    In some plain-text editions, dialogue-attribution lines are separated
    from their spoken text by blank lines:

        He looked attentively, then:

        "No! That one is already very ill."

        He replied,

        "It does not matter. Draw me a sheep."

    PySBD splits these at the blank line, producing fragment sentences
    like 'He looked attentively, then:' or 'He replied,'.  Collapse the
    whitespace so PySBD sees the attribution and dialogue as one sentence.
    """
    return _DIALOGUE_ATTRIBUTION_RE.sub(r'\1 "', text)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using PySBD."""
    text = _normalize_dialogue_attribution(text)
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    seg = _get_segmenter()
    sentences = seg.segment(text)
    sentences = [_clean_quote_artifact(s.strip()) for s in sentences]
    return [s for s in sentences if s]


def _strip_non_alpha(text: str) -> str:
    """Strip all non-letter characters for source-text verification."""
    return re.sub(r'[^a-zA-Z]', '', text.lower())


def _clean_quote_artifact(sentence: str) -> str:
    """Remove PySBD dangling-quote artifacts from dialogue splitting."""
    return re.sub(r'^\"\s+\"', '"', sentence)


def hard_truncate(sentence: str, max_len: int = HARD_CUTOFF) -> tuple[str, bool]:
    """Truncate at the last word boundary within max_len chars."""
    if len(sentence) <= max_len:
        return sentence, False
    truncated = sentence[:max_len].rstrip()
    last_space = truncated.rfind(' ')
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip(), True


def _has_be_to_pattern(doc, token_idx: int) -> bool:
    """Check if a token is a psychological adjective in 'be ADJ/VBN to VERB' pattern.

    E.g. 'was astonished to see', 'am surprised to hear'.
    Modern spaCy models (en_core_web_sm) often tag these as ADJ/JJ
    rather than VBN, so we accept both.
    """
    token = doc[token_idx]
    if token.tag_ not in ("VBN", "JJ"):
        return False
    # ADJ tokens: only check if dep is acomp/acmp/oprd (predicate adjective).
    # attr is for "X is Y" — not "be ADJ to VERB".
    if token.tag_ == "JJ" and token.dep_ not in ("acomp", "oprd"):
        return False
    be_forms = {'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being'}
    # Check for be-form before the token
    has_be = any(
        doc[i].text.lower() in be_forms
        for i in range(max(0, token_idx - 3), token_idx)
    )
    if not has_be:
        return False
    # Check for "to" after the token, followed by a VERB
    for j in range(token_idx + 1, min(token_idx + 3, len(doc))):
        if doc[j].text.lower() == 'to' and j + 1 < len(doc):
            if doc[j + 1].pos_ == 'VERB':
                return True
            break
    return False


def _determine_lemma(token, word: str) -> str:
    """Determine the lemma for a word based on spaCy token analysis.

    Returns the surface form (word) when it's an adjective or derivation
    that should not be reduced.  Otherwise passes to lemminflect with the
    correct POS channel.
    """
    import lemminflect

    wl = word.lower()

    # Signal 1: POS tag — spaCy directly tags as ADJ
    if token.pos_ == "ADJ":
        return wl

    # Signal 2: adjectival dependency relation.
    # attr is NOT included — it applies to both nouns and adjectives
    # in predicate position (e.g. "He is a teacher" vs "He is tall").
    if token.dep_ in ("acomp", "amod", "oprd"):
        return wl

    # Signal 3: VBG + adjectival dep — participial adjective
    if token.tag_ == "VBG" and token.dep_ in ("amod", "acomp"):
        return wl

    # Signal 4: PROPN — proper noun.  Lowercase PROPN is almost always
    # a spaCy mis-classification (genuine proper nouns are capitalised).
    # Sentence-initial tokens are also likely mis-classified (capitalised
    # due to position, not because they are proper nouns).
    # Must be checked BEFORE spacy_lemma==word (PROPN tokens lemma==text).
    if token.pos_ == "PROPN":
        if word[0].islower() or token.i == 0:
            lemmas = lemminflect.getLemma(wl, 'NOUN')
            if lemmas:
                return lemmas[0]
        return wl

    # Signal 5: spaCy lemma == surface form — refuses to reduce
    if token.lemma_.lower() == wl:
        return wl

    # Signal 6: ADV ending in -ly — don't reduce
    if token.pos_ == "ADV" and wl.endswith('ly'):
        return wl

    # lemminflect with the correct POS channel
    channel_map = {'VERB': 'VERB', 'NOUN': 'NOUN', 'ADJ': 'ADJ', 'ADV': 'ADV'}
    channel = channel_map.get(token.pos_)
    if channel:
        lemmas = lemminflect.getLemma(wl, channel)
        if lemmas:
            return lemmas[0]

    return wl


def _better(old: dict, new: dict) -> bool:
    """Return True if *new* sentence is better than *old*.

    Three-tier comparison (pure logic, no scoring):
      1. sweet-spot (30-250 chars): shorter wins
      2. too-long (>250): shorter wins
      3. too-short (<30): longer wins
    Cross-tier: sweet-spot > too-long > too-short.
    Tie (same length): keep old.
    """
    la, lb = old['len'], new['len']
    if la == lb:
        return False                                             # tie → keep old
    if (la < 30 or lb < 30) ^ (la < lb):
        return False                                             # keep old
    return True                                                  # pick new


def _cmu_ipa(word: str) -> str:
    """Look up IPA from cmudict."""
    from lib.ipa import _cmu_ipa
    return _cmu_ipa(word) or ""


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <filter_json> <source_text>", file=sys.stderr)
        print("  filter_json : JSON from filter_fulltext.py", file=sys.stderr)
        print("  source_text : plain text of the book (English, full text)", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    text_path = sys.argv[2]

    with open(json_path) as f:
        data = json.load(f)

    with open(text_path) as f:
        text = f.read()

    # Reject non-English source texts
    if re.search(r'[Ѐ-ӿ«»]', text):
        print("ERROR: Source text contains Cyrillic or guillemet characters.",
              file=sys.stderr)
        sys.exit(1)

    # ── preamble detection ──────────────────────────────────────────────
    start_offset = 0
    for i, arg in enumerate(sys.argv):
        if arg == '--start-offset' and i + 1 < len(sys.argv):
            start_offset = int(sys.argv[i + 1])
            break

    if start_offset == 0:
        story_start = detect_story_start(text)
        if story_start > 0:
            print(f"  [info] Preamble skipped: {story_start} chars", file=sys.stderr)
            start_offset = story_start

    # ── load spaCy ───────────────────────────────────────────────────────
    import spacy
    from lib.utils import _get_spacy

    nlp = _get_spacy(enable_parser=True)
    if nlp is None:
        print("ERROR: spaCy not available", file=sys.stderr)
        sys.exit(1)

    words = data['in_coca']
    total = len(words)

    # ── Step 1: split sentences once ─────────────────────────────────────
    sentences = split_sentences(text[start_offset:])
    text_normalized = _strip_non_alpha(text)
    print(f"  Sentences: {len(sentences)}", file=sys.stderr)

    # ── Step 2: build form → [(idx, entry)] index ───────────────────────
    form_index: dict[str, list[tuple[int, dict]]] = {}
    for idx, entry in enumerate(words):
        for form in entry['forms']:
            key = form.lower()
            if key not in form_index:
                form_index[key] = []
            form_index[key].append((idx, entry))

    # ── Step 3: incremental best-entry state ────────────────────────────
    groups: dict[tuple[str, str], dict] = {}       # (lemma, pos) → best entry
    group_sources: dict[tuple[str, str], set] = {}  # (lemma, pos) → set of word indices
    matched_indices: set = set()

    # ── Step 4: single pass over sentences ──────────────────────────────
    TOTAL_SENTS = len(sentences)
    for si, raw_sentence in enumerate(sentences):
        # --- normalise whitespace ---
        sentence = re.sub(r' {2,}', ' ', raw_sentence)
        sentence = re.sub(r'\t+', ' ', sentence).strip()
        if not sentence:
            continue

        # --- pre-filter: quick token match before running spaCy ---
        pre_tokens = set(
            t.lower() for t in re.findall(r'\b[a-zA-Z]{2,}\b', sentence)
        )
        if not any(t in form_index for t in pre_tokens):
            continue

        # --- source-text verification (pre-truncation) ---
        if _strip_non_alpha(sentence) not in text_normalized:
            continue

        # --- hard truncate ---
        truncated, was_truncated = hard_truncate(sentence)

        # --- spaCy analysis (once per sentence) ---
        doc = nlp(truncated)

        sent_len = len(truncated)

        # --- iterate doc tokens, match against form_index ---
        seen_entries: set[int] = set()  # (idx, token.text.lower()) per sentence
        for token in doc:
            if not token.is_alpha or len(token.text) < 2:
                continue

            token_lower = token.text.lower()
            hits = form_index.get(token_lower)
            if not hits:
                continue

            for idx, entry in hits:
                # Prevent re-processing the same (entry index, token text)
                # within the same sentence (e.g. "walked" appearing twice).
                sent_key = (idx, token_lower)
                if sent_key in seen_entries:
                    continue
                seen_entries.add(sent_key)

                # Determine lemma from this specific token context
                lemma = _determine_lemma(token, token.text)
                pos = token.pos_

                # be-to pattern check for VBN tokens.
                # Run unconditionally — even when _determine_lemma already
                # returned the surface form (via other ADJ signals), we
                # need be_to=True in the output.  Only override lemma/POS
                # when _determine_lemma did NOT already do so.
                has_be_to = (
                    token.tag_ in ("VBN", "JJ")
                    and _has_be_to_pattern(doc, token.i)
                )
                if has_be_to and lemma != token_lower:
                    lemma = token_lower
                    pos = "ADJ"

                # PROPN→NOUN: lowercase, sentence-initial, or known-vocabulary
                # proper nouns.  Mid-sentence capitalized common nouns
                # (e.g. "Boa" in "book, Boa constrictors") are spaCy
                # mis-classifications — convert if the word is in our filter.
                if pos == "PROPN" and (token.text[0].islower() or token.i == 0
                                       or token_lower in form_index):
                    pos = "NOUN"
                # conj POS inheritance: in coordinated structures
                # (A, B, C and D), spaCy sometimes mis-tags individual
                # conjuncts (e.g. "arithmetic" as ADJ in a list of NOUNs).
                # Walk up the conj chain to the coordination root and
                # inherit its POS when the root has a reliable POS tag.
                if token.dep_ == "conj":
                    head_token = token.head
                    while head_token.dep_ == "conj":
                        head_token = head_token.head
                    head_pos = head_token.pos_
                    if head_pos in ("NOUN", "VERB", "ADJ", "ADV") and pos != head_pos:
                        pos = head_pos
                # Sentence-initial inverted ADJ: "Absurd as it might seem"
                # (= "As absurd as ...").  spaCy often tags these as PROPN
                # (capitalized at sentence start); PROPN→NOUN then converts
                # to NOUN.  Detect the "X as" pattern with dep guard
                # (advcl for inverted adjective clauses, not npadvmod for
                # noun phrases like "King as he was").
                if (pos == "NOUN" and token.i == 0
                        and token.dep_ in ("advcl", "root", "ROOT")):
                    if (token.i + 1 < len(doc)
                            and doc[token.i + 1].text.lower() == "as"):
                        import lemminflect
                        adj_lemmas = lemminflect.getLemma(token_lower, 'ADJ')
                        if adj_lemmas and adj_lemmas[0] == token_lower:
                            pos = "ADJ"
                # NOUN/VERB→ADJ: adjectival dependency overrides POS tag.
                # attr is excluded — it applies to both nouns ("a teacher")
                # and adjectives ("tall") in predicate position.
                if pos in ("NOUN", "VERB") and token.dep_ in ("amod", "acomp", "oprd"):
                    pos = "ADJ"
                # NOUN+compound→ADJ: spaCy mis-tags some adjectives as noun
                # compounds (e.g. "primeval forests").  Adjective suffixes
                # help distinguish from genuine noun compounds ("stone wall").
                _ADJ_SUFFIXES = ("al", "ic", "ous", "ive", "ful", "less", "able", "ible")
                if (pos == "NOUN" and token.dep_ == "compound"
                        and token.text.lower().endswith(_ADJ_SUFFIXES)):
                    pos = "ADJ"

                key = (lemma, pos)

                cand = {
                    'text': truncated,
                    'len': sent_len,
                    'target_offset': token.idx,
                    'matched_form': token.text,
                    'lemma': lemma,
                    'pos': pos,
                    'dep': token.dep_,
                    'spacy_lemma': token.lemma_,
                    'be_to': has_be_to,
                    'truncated': was_truncated,
                }

                if key not in groups or _better(groups[key], cand):
                    groups[key] = cand

                if key not in group_sources:
                    group_sources[key] = set()
                group_sources[key].add(idx)
                matched_indices.add(idx)

        print(f"\r  {si+1}/{TOTAL_SENTS}", end='', file=sys.stderr, flush=True)

    print(file=sys.stderr)

    # ── Step 5: post-process output ─────────────────────────────────────
    results = []
    for key, cand in groups.items():
        lemma, pos = key
        indices = group_sources.get(key, set())

        # Merge forms from all source entries
        all_forms: list[str] = []
        for idx in indices:
            entry = words[idx]
            for f in entry['forms']:
                fl = f.lower()
                if fl not in all_forms:
                    all_forms.append(fl)
        all_forms.sort()

        # coca_level from first source entry that has one
        coca_level = None
        for idx in indices:
            lvl = words[idx].get('coca_level')
            if lvl is not None:
                coca_level = lvl
                break

        # char_offset: first occurrence in story body
        char_offset = -1
        for form in all_forms:
            pos_val = text.lower().find(form.lower(), start_offset)
            if pos_val >= 0:
                char_offset = pos_val
                break

        # IPA: try lemma first, fall back to matched surface form
        ipa = _cmu_ipa(lemma) or _cmu_ipa(cand['matched_form'])

        results.append({
            'lemma': lemma,
            'word': cand['matched_form'],
            'forms': all_forms,
            'pos': cand['pos'],
            'dep': cand.get('dep', ''),
            'spacy_lemma': cand.get('spacy_lemma', ''),
            'be_to': cand.get('be_to', False),
            'coca_level': coca_level,
            'sentence': cand['text'],
            'target_offset': cand['target_offset'],
            'char_offset': char_offset,
            'ipa': ipa,
        })

    # Sort results for deterministic output (by lemma, then pos)
    results.sort(key=lambda r: (r['lemma'], r['pos']))

    # no_sentence: word entries without any match
    no_sentence = []
    for idx, entry in enumerate(words):
        if idx not in matched_indices:
            surface = entry.get('lemma', '')
            forms = entry.get('forms', [])
            no_sentence.append((surface, forms))

    if no_sentence:
        print(f"\nNo sentence found ({len(no_sentence)}):", file=sys.stderr)
        for surface, forms in no_sentence:
            print(f"  [{surface}] forms={forms}", file=sys.stderr)

    print(f"  Words matched: {len(matched_indices)}/{total} → {len(results)} (lemma,pos) groups",
          file=sys.stderr)

    output = {
        'book_title': data.get('book_title', ''),
        'book_author': data.get('book_author', ''),
        'deck_name': data.get('deck_name', ''),
        'source_text_path': text_path,
        'suffix': data.get('suffix', ''),
        'words': results,
        'excluded': data.get('excluded', []),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
