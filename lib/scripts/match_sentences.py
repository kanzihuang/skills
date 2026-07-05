#!/usr/bin/env python3
"""Step 3.0: Mechanical sentence matching from source text.

Reads filter_fulltext.py JSON output and source text, extracts candidate
sentences per word with <b> surface form tagging.  Uses PySBD for sentence
segmentation (97.92% accuracy on Golden Rule set).

Pre-selects the best candidate per word via select_best_sentence() —
a three-tier mechanical rule (sweet-spot ≥ short ≥ long) that chooses
the optimal sentence without consuming Claude context.

No semantic truncation — that is handled by Step 3A (Claude).  Only a hard
500-char cutoff guards against extreme outliers.
"""

import json
import os
import re
import sys

import pysbd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.config import MAX_CANDIDATES, HARD_CUTOFF, MIN_SENTENCE_LENGTH, MAX_SENTENCE_LENGTH


def _get_segmenter() -> pysbd.Segmenter:
    """Return a cached PySBD segmenter (lazy init)."""
    return pysbd.Segmenter(language="en", clean=True)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences using PySBD.

    PySBD is a pure-rule engine (no model weights) with 97.92% accuracy.
    It handles abbreviations (Dr., Mr., U.S.), dialogue quotes, and
    parenthetical punctuation correctly.
    """
    # Normalize newlines: double→paragraph break, single→space
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)

    seg = _get_segmenter()
    sentences = seg.segment(text)
    sentences = [_clean_quote_artifact(s.strip()) for s in sentences]
    return [s for s in sentences if s]


def _strip_non_alpha(text: str) -> str:
    """Strip all non-letter characters for source-text verification.

    Only the letter sequence matters for matching — whitespace,
    punctuation, and newline differences from PySBD clean=True
    processing are irrelevant to correctness.
    """
    return re.sub(r'[^a-zA-Z]', '', text.lower())


def _clean_quote_artifact(sentence: str) -> str:
    """Remove PySBD dangling-quote artifacts from dialogue splitting.

    PySBD splits at ." boundaries, leaving a closing quote from the
    previous dialogue as a leading character on the next sentence.
    E.g. '\" \"No,' → '\"No,'
    """
    return re.sub(r'^\"\s+\"', '"', sentence)


def hard_truncate(sentence: str, max_len: int = HARD_CUTOFF) -> tuple[str, bool]:
    """Truncate at the last word boundary within max_len chars.

    Returns (sentence, was_truncated).  Only truncates when the sentence
    exceeds max_len — this is a mechanical safety net for extreme outliers
    (>500 chars), NOT semantic truncation.
    """
    if len(sentence) <= max_len:
        return sentence, False

    # Find last space within max_len
    truncated = sentence[:max_len].rstrip()
    last_space = truncated.rfind(' ')
    if last_space > 0:
        truncated = truncated[:last_space]

    return truncated.rstrip(), True


def find_all_sentences(
    text: str, word_forms: list[str], lemma: str
) -> list[dict]:
    """Find all sentences containing any of the word's surface forms.

    Returns up to MAX_CANDIDATES sentences, in original text order.
    Each result is {"text": "<b>tagged</b> sentence", "len": N, "truncated": bool}.

    Only candidates that pass source-text verification are included.
    """
    sentences = split_sentences(text)
    text_normalized = _strip_non_alpha(text)

    seen = set()  # deduplicate identical sentences
    results = []

    for sent in sentences:
        if len(results) >= MAX_CANDIDATES:
            break

        for form in word_forms:
            pattern = re.compile(r'\b' + re.escape(form) + r'\b', re.IGNORECASE)
            m = pattern.search(sent)
            if not m:
                continue

            matched_text = m.group(0)
            tagged = sent[:m.start()] + f'<b>{matched_text}</b>' + sent[m.end():]

            # Normalize whitespace: collapse multiple spaces (OCR artifacts
            # from scanned source texts like Internet Archive).
            tagged = re.sub(r' {2,}', ' ', tagged)
            tagged = re.sub(r'\t+', ' ', tagged)

            # Source-text verification: compare letter sequences only.
            # Whitespace, punctuation, and newline differences from
            # PySBD clean=True don't affect the match.
            clean = re.sub(r'<[^>]+>', '', tagged)
            if _strip_non_alpha(clean) not in text_normalized:
                continue

            # <b> tag verification: tagged text must match the word form
            b_text = matched_text
            if b_text.lower() not in [f.lower() for f in word_forms]:
                continue

            # Hard truncate if needed (>500 chars)
            truncated_tagged, was_truncated = hard_truncate(tagged)
            truncated_clean = re.sub(r'<[^>]+>', '', truncated_tagged)
            plain_len = len(truncated_clean)

            sent_key = ' '.join(clean.split())
            if sent_key not in seen:
                seen.add(sent_key)
                results.append({
                    'text': truncated_tagged,
                    'len': plain_len,
                    'truncated': was_truncated,
                })

            break  # found a matching form for this sentence

    return results


def select_best_sentence(
    candidates: list[dict],
    min_len: int = MIN_SENTENCE_LENGTH,
    max_len: int = MAX_SENTENCE_LENGTH,
) -> dict | None:
    """Select the best candidate sentence by mechanical rule.

    Three-tier selection (data-informed thresholds):
    1. Candidates with min_len ≤ len ≤ max_len → pick shortest
       (ideal: enough context, no truncation needed)
    2. Only candidates > max_len remain → pick shortest
       (must truncate, but better than a <30-char sentence with no context)
    3. All candidates < min_len → pick longest
       (best effort — all are <30 chars, truly insufficient context)

    Returns None only if candidates list is empty.
    """
    if not candidates:
        return None

    # Tier 1: sweet spot — e.g. 30 ≤ len ≤ 250
    sweet_spot = [c for c in candidates if min_len <= c['len'] <= max_len]
    if sweet_spot:
        return min(sweet_spot, key=lambda c: c['len'])

    # Tier 2: only candidates > max_len — pick shortest (must truncate)
    long = [c for c in candidates if c['len'] > max_len]
    if long:
        return min(long, key=lambda c: c['len'])

    # Tier 3: all candidates < min_len — pick longest (best effort)
    return max(candidates, key=lambda c: c['len'])


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <filter_json> <source_text>", file=sys.stderr)
        print("  filter_json : JSON from filter_pipeline.py / filter_fulltext.py", file=sys.stderr)
        print("  source_text : plain text of the book (English, full text)", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    text_path = sys.argv[2]

    with open(json_path) as f:
        data = json.load(f)

    with open(text_path) as f:
        text = f.read()

    # Reject non-English source texts.
    if re.search(r'[Ѐ-ӿ«»]', text):
        print(
            "ERROR: Source text contains Cyrillic or guillemet (non-English) "
            "characters.  Use an English-only edition — bilingual texts "
            "produce contaminated sentences.",
            file=sys.stderr,
        )
        sys.exit(1)

    words = data['in_coca']
    total = len(words)
    results = []
    no_sentence = []

    for i, entry in enumerate(words):
        lemma = entry['lemma']
        forms = entry['forms']
        candidates = find_all_sentences(text, forms, lemma)

        # Compute char_offset: first occurrence position of any form
        char_offset = -1
        for form in forms:
            pos = text.lower().find(form.lower())
            if pos >= 0:
                char_offset = pos
                break

        if not candidates:
            no_sentence.append((lemma, forms))

        selected = select_best_sentence(candidates)

        results.append({
            'lemma': lemma,
            'rep': entry['rep'],
            'forms': forms,
            'candidates': candidates,
            'selected': selected,
            'char_offset': char_offset,
        })

        print(f"\r  {i+1}/{total} {lemma} ({len(candidates)} candidate(s))",
              end='', file=sys.stderr, flush=True)

    print(file=sys.stderr)

    if no_sentence:
        print(f"\nNo sentence found ({len(no_sentence)}):", file=sys.stderr)
        for lemma, forms in no_sentence:
            print(f"  [{lemma}] forms={forms}", file=sys.stderr)

    output = {
        'book_title': data.get('book_title', ''),
        'book_author': data.get('book_author', ''),
        'deck_name': data.get('deck_name', ''),
        'source_text_path': text_path,
        'words': results,
        'excluded': data.get('excluded', []),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
