#!/usr/bin/env python3
"""Step 2A: Mechanical sentence matching + POS-aware lemmatization.

Reads filter_fulltext.py JSON output and source text, extracts all candidate
sentences per word, runs spaCy on each to determine POS and lemma, groups by
(lemma, pos), selects the best sentence per group, and fills cmudict IPA.

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


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using PySBD."""
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


def _has_be_to_pattern(doc, vbn_idx: int) -> bool:
    """Check if a VBN token is a psychological adjective in 'be VBN to VERB' pattern.

    E.g. 'was astonished to see', 'am surprised to hear'.
    """
    token = doc[vbn_idx]
    if token.tag_ != "VBN":
        return False
    be_forms = {'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being'}
    # Check for be-form before the token
    has_be = any(
        doc[i].text.lower() in be_forms
        for i in range(max(0, vbn_idx - 3), vbn_idx)
    )
    if not has_be:
        return False
    # Check for "to" after the token, followed by a VERB
    for j in range(vbn_idx + 1, min(vbn_idx + 3, len(doc))):
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

    # Signal 2: adjectival dependency relation
    if token.dep_ in ("acomp", "amod", "attr", "oprd"):
        return wl

    # Signal 3: VBG + amod — participial adjective
    if token.tag_ == "VBG" and token.dep_ == "amod":
        return wl

    # Signal 4: PROPN — proper noun.  Lowercase PROPN is almost always
    # a spaCy mis-classification (genuine proper nouns are capitalised).
    # Must be checked BEFORE spacy_lemma==word (PROPN tokens lemma==text).
    if token.pos_ == "PROPN":
        if word[0].islower():
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


def find_all_sentences(text: str, word_forms: list[str],
                       start_offset: int = 0) -> list[dict]:
    """Find all sentences containing any of the word's surface forms.

    Returns ALL sentences (no candidate cap), in original text order.
    Each result is {"text": clean_sentence, "len": N, "target_offset": int,
    "truncated": bool}.

    Sentences are stored WITHOUT <b> tags.
    """
    search_text = text[start_offset:]
    sentences = split_sentences(search_text)
    text_normalized = _strip_non_alpha(text)

    seen = set()
    results = []

    for sent in sentences:
        for form in word_forms:
            pattern = re.compile(r'\b' + re.escape(form) + r'\b', re.IGNORECASE)
            m = pattern.search(sent)
            if not m:
                continue

            matched_text = m.group(0)

            # Normalize whitespace first, then find offset in clean text
            clean = re.sub(r' {2,}', ' ', sent)
            clean = re.sub(r'\t+', ' ', clean)
            # Re-match in the normalized text for correct offset
            clean_m = pattern.search(clean)
            if clean_m:
                target_offset = clean_m.start()
                matched_text = clean_m.group(0)
            else:
                target_offset = m.start()

            # Source-text verification
            if _strip_non_alpha(clean) not in text_normalized:
                continue

            # Verify matched text is a valid surface form
            if matched_text.lower() not in [f.lower() for f in word_forms]:
                continue

            # Hard truncate if needed (>500 chars)
            truncated_clean, was_truncated = hard_truncate(clean)
            plain_len = len(truncated_clean)

            sent_key = ' '.join(clean.split())
            if sent_key not in seen:
                seen.add(sent_key)
                results.append({
                    'text': truncated_clean,
                    'len': plain_len,
                    'target_offset': min(target_offset, len(truncated_clean) - 1),
                    'matched_form': matched_text,
                    'truncated': was_truncated,
                })

            break  # found a matching form for this sentence

    return results


def select_best_sentence(candidates: list[dict],
                         min_len: int = MIN_SENTENCE_LENGTH,
                         max_len: int = MAX_SENTENCE_LENGTH) -> dict | None:
    """Select the best candidate sentence by mechanical rule.

    Three-tier selection:
    1. Candidates with min_len ≤ len ≤ max_len → pick shortest
    2. Only candidates > max_len → pick shortest
    3. All candidates < min_len → pick longest
    """
    if not candidates:
        return None

    sweet_spot = [c for c in candidates if min_len <= c['len'] <= max_len]
    if sweet_spot:
        return min(sweet_spot, key=lambda c: c['len'])

    long = [c for c in candidates if c['len'] > max_len]
    if long:
        return min(long, key=lambda c: c['len'])

    return max(candidates, key=lambda c: c['len'])


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
    results = []
    no_sentence = []

    for i, entry in enumerate(words):
        surface = entry['lemma']  # filter stores surface form in 'lemma' field
        forms = entry['forms']

        # Find all sentences for this surface form
        candidates = find_all_sentences(text, forms, start_offset=start_offset)

        # Compute char_offset: first occurrence in the story body
        char_offset = -1
        for form in forms:
            pos = text.lower().find(form.lower(), start_offset)
            if pos >= 0:
                char_offset = pos
                break

        if not candidates:
            no_sentence.append((surface, forms))
            continue

        # ── spaCy analysis per candidate + group by (lemma, pos) ────────
        groups: dict[tuple[str, str], list[dict]] = {}

        for cand in candidates:
            clean_text = cand['text']
            doc = nlp(clean_text)

            # Find the target token by position
            target_token = None
            for token in doc:
                if token.idx <= cand['target_offset'] < token.idx + len(token.text):
                    if token.text.lower() == cand['matched_form'].lower():
                        target_token = token
                        break

            # Fallback: match by text if position-based match fails
            if target_token is None:
                for token in doc:
                    if token.text.lower() == cand['matched_form'].lower():
                        target_token = token
                        break

            if target_token is None:
                continue  # skip this candidate if we can't find the token

            # Determine lemma
            lemma = _determine_lemma(target_token, cand['matched_form'])

            # Additional check: be-to pattern for VBN tokens
            if target_token.tag_ == "VBN" and lemma != cand['matched_form'].lower():
                if _has_be_to_pattern(doc, target_token.i):
                    lemma = cand['matched_form'].lower()

            # Store analysis results on the candidate.
            # For lowercase PROPN (spaCy mis-tag), override pos to NOUN.
            pos_val = target_token.pos_
            if pos_val == "PROPN" and cand['matched_form'][0].islower():
                pos_val = "NOUN"
            cand['pos'] = pos_val
            cand['dep'] = target_token.dep_
            cand['spacy_lemma'] = target_token.lemma_
            cand['lemma'] = lemma
            cand['be_to'] = (
                target_token.tag_ == "VBN" and
                _has_be_to_pattern(doc, target_token.i)
            )

            key = (lemma, target_token.pos_)
            groups.setdefault(key, []).append(cand)

        # ── select best per group ───────────────────────────────────────
        for (lemma, pos_val), group_cands in groups.items():
            selected = select_best_sentence(group_cands)
            if selected is None:
                continue

            # cmudict IPA: try lemma first, fall back to surface form
            ipa = _cmu_ipa(lemma) or _cmu_ipa(selected['matched_form'])

            # Collect remaining candidates (from same group) for Step 2B fallback
            other_cands = [
                {"text": c['text'], "len": c['len'], "target_offset": c['target_offset']}
                for c in group_cands if c is not selected
            ]

            results.append({
                'lemma': lemma,
                'word': selected['matched_form'],
                'forms': forms,
                'pos': selected.get('pos', ''),
                'dep': selected.get('dep', ''),
                'spacy_lemma': selected.get('spacy_lemma', ''),
                'be_to': selected.get('be_to', False),
                'coca_level': entry.get('coca_level'),
                'sentence': selected['text'],
                'target_offset': selected['target_offset'],
                'char_offset': char_offset,
                'ipa': ipa,
                'candidates': other_cands,
            })

        print(f"\r  {i+1}/{total} {surface} ({len(groups)} group(s))",
              end='', file=sys.stderr, flush=True)

    print(file=sys.stderr)

    if no_sentence:
        print(f"\nNo sentence found ({len(no_sentence)}):", file=sys.stderr)
        for lemma, forms in no_sentence:
            print(f"  [{lemma}] forms={forms}", file=sys.stderr)

    # ── cross-entry dedup by (lemma, pos) ───────────────────────────
    # Different filter entries may produce the same (lemma, pos) after
    # lemmatization (e.g. "constrictor" + "constrictors" → both
    # (constrictor, NOUN)).  Merge them, keeping the best sentence.
    deduped: dict[tuple[str, str], dict] = {}
    for w in results:
        key = (w['lemma'], w['pos'])
        if key in deduped:
            existing = deduped[key]
            # Merge: keep the better sentence (prefer 30-250 range)
            existing_cands = existing.get('candidates', [])
            new_cands = w.get('candidates', [])
            all_cands = [existing, w] + existing_cands + new_cands
            best = select_best_sentence([
                {'text': c['sentence'] if 'sentence' in c else c['text'],
                 'len': len(c['sentence'] if 'sentence' in c else c['text'])}
                for c in [existing, w]
            ])
            if best and best['text'] != existing['sentence']:
                # New entry has better sentence — swap
                existing['sentence'] = w['sentence']
                existing['target_offset'] = w['target_offset']
                existing['word'] = w['word']
            # Merge forms and candidates
            existing['forms'] = sorted(set(existing.get('forms', []) + w.get('forms', [])))
            existing['candidates'] = list({
                c['text']: c for c in (
                    existing.get('candidates', []) +
                    w.get('candidates', []) +
                    [{'text': existing['sentence'], 'len': len(existing['sentence']),
                      'target_offset': existing['target_offset']},
                     {'text': w['sentence'], 'len': len(w['sentence']),
                      'target_offset': w['target_offset']}]
                )
            }.values())
            # Remove the winning sentence from candidates
            existing['candidates'] = [
                c for c in existing['candidates']
                if c['text'] != existing['sentence']
            ]
        else:
            deduped[key] = w

    results = list(deduped.values())

    print(f"  After dedup: {len(results)} entries", file=sys.stderr)

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
