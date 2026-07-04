#!/usr/bin/env python3
"""Step 3.0: Mechanical sentence matching from source text.

Reads filter_fulltext.py JSON output and source text, extracts candidate
sentences per word with <b> surface form tagging.  Uses PySBD for sentence
segmentation (97.92% accuracy on Golden Rule set).

No semantic truncation — that is handled by Step 3A (Claude).  Only a hard
500-char cutoff guards against extreme outliers.
"""

import json
import re
import sys

import pysbd

MAX_CANDIDATES = 5
HARD_CUTOFF = 500


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


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/vocab-anki-filtered-3300144556.json'
    text_path = sys.argv[2] if len(sys.argv) > 2 else '/tmp/oldmansea_full.txt'

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

        results.append({
            'lemma': lemma,
            'rep': entry['rep'],
            'forms': forms,
            'candidates': candidates,
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
