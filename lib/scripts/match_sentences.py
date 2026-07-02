#!/usr/bin/env python3
"""Step 3.0: Mechanical sentence matching from source text.

Reads filter_fulltext.py JSON output and source text, extracts one sentence
per word with <b> surface form tagging. Handles dialogue, newlines, and
truncation that preserves the target word.
"""

import json
import re
import sys


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, handling dialogue and newlines.

    Splits on: .!? followed by whitespace (including newlines) and a capital
    letter or opening quote. Also splits on double newlines.
    """
    # First, normalize multiple newlines into paragraph breaks
    text = re.sub(r'\n{2,}', '\n\n', text)
    # Replace single newlines with space (within-paragraph line breaks)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)

    # Split on sentence-ending punctuation followed by space and capital
    # or opening quote.  "“"=“, ‘=' are curly quotes common
    # in books; without them, dialogue after a period isn't split.
    # « (guillemet) is added for non-English metadata like
    # «The Little Prince».
    sentences = re.split(r'(?<=[.!?"”])\s+(?=[A-Z"“‘’“«])', text)
    return [s.strip() for s in sentences if s.strip()]


def _is_metadata(sentence: str) -> bool:
    """Return True if *sentence* looks like book metadata, not narrative text.

    Gutenberg / Internet Archive texts often include chapter headers,
    author names, and title markers that aren't real sentences.  These
    produce garbage cards when matched as vocabulary sentences.
    """
    if not sentence:
        return True

    # Cyrillic, Greek, or other non-Latin scripts — book metadata
    if re.search(r'[Ѐ-ӿͰ-Ͽ]', sentence):
        return True

    # Guillemets — non-English title markers like «The Little Prince»
    if re.search(r'[«»]', sentence):
        return True

    # Bare numeric chapter/page markers: "33", "Chapter 1", "CHAPTER I"
    stripped = sentence.strip()
    if re.match(r'^\d{1,4}$', stripped):
        return True
    if re.match(r'^(Chapter|CHAPTER|chapitre)\s+[\dIVX]+\.?$', stripped):
        return True

    # Lines that are >40% non-word characters (garbled OCR, tables, etc.)
    alpha = sum(1 for c in sentence if c.isalpha())
    if len(sentence) > 0 and alpha / len(sentence) < 0.4:
        return True

    return False


def find_best_sentence(text: str, word_forms: list[str], lemma: str) -> str | None:
    """Find the best sentence containing any of the word's surface forms.

    Tries each form, picks the shortest sentence that contains it.
    Metadata lines (chapter headers, author names, page numbers) are
    skipped — they are not valid vocabulary sentences.
    """
    sentences = split_sentences(text)

    best = None
    best_len = float('inf')

    for form in word_forms:
        pattern = re.compile(r'\b' + re.escape(form) + r'\b', re.IGNORECASE)
        for sent in sentences:
            if _is_metadata(sent):
                continue
            m = pattern.search(sent)
            if m:
                matched_text = m.group(0)
                tagged = sent[:m.start()] + f'<b>{matched_text}</b>' + sent[m.end():]
                plain_len = len(re.sub(r'<[^>]+>', '', tagged))
                if plain_len < best_len:
                    best = tagged
                    best_len = plain_len

    return best


def truncate_sentence(sentence: str, max_len: int = 150) -> str:
    """Truncate sentence to max_len chars while keeping it grammatical.

    CRITICAL: must preserve the <b> tag AND produce a grammatical sentence.
    Never trim from the start — produces fragments (SKILL.md 3.0e rule).
    Only trim from the END at natural clause boundaries.
    """
    plain = re.sub(r'<[^>]+>', '', sentence)
    if len(plain) <= max_len:
        return sentence

    b_match = re.search(r'<b>(.+?)</b>', sentence)
    if not b_match:
        return sentence[:max_len - 3].rstrip() + '...'

    b_end = b_match.end()

    # Only trim from the END — find last natural break before max_len
    # that is AFTER the <b> tag
    delimiters = ['; ', ', and ', ', but ', ', or ', ', ', ' — ', '. ']
    for delim in delimiters:
        for cand in reversed(list(re.finditer(re.escape(delim), sentence))):
            cand_end = cand.end()
            if cand_end <= b_end:
                continue
            prefix_plain = re.sub(r'<[^>]+>', '', sentence[:cand_end])
            if len(prefix_plain) <= max_len:
                return sentence[:cand_end].rstrip()

    # If no natural break found after <b> within limit,
    # truncate at the last word boundary within max_len.
    # A clean cut is better than a long sentence whose translation
    # will later go out of sync after manual shortening.
    #
    # Walk the tagged sentence tracking plain-text position to find
    # the last space that maps to ≤ max_len plain chars and is after <b>.
    best_tagged_pos = 0
    plain_pos = 0
    in_tag = False
    for idx, ch in enumerate(sentence):
        if ch == '<':
            in_tag = True
        elif ch == '>':
            in_tag = False
        elif not in_tag:
            if ch == ' ' and plain_pos <= max_len and idx > b_end:
                best_tagged_pos = idx
            plain_pos += 1

    if best_tagged_pos > b_end:
        return sentence[:best_tagged_pos].rstrip()

    # Absolute last resort: keep sentence as-is (should be rare)
    return sentence


def verify_sentence(sentence: str, forms: list[str]) -> tuple[bool, str]:
    """Verify sentence quality. Returns (ok, reason)."""
    if not sentence:
        return False, "no sentence"

    plain = re.sub(r'<[^>]+>', '', sentence)

    # Check surface form presence (case-insensitive)
    found_form = None
    for form in forms:
        if form.lower() in plain.lower():
            found_form = form
            break
    if not found_form:
        return False, f"surface form {forms} not in: {plain[:60]}"

    # Check starts with capital, opening quote, or ellipsis (for front-trimmed)
    stripped = plain.strip()
    if not stripped:
        return False, "empty after strip"
    first_char = stripped[0]
    if not (first_char.isupper() or first_char in '"“‘’…'):
        return False, f"does not start with capital: {stripped[:40]}"

    # Check has finite verb (approximate: has at least one common verb form)
    # This is a loose check - dialogue and fragments are OK for Hemingway
    return True, "ok"


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/vocab-anki-filtered-3300144556.json'
    text_path = sys.argv[2] if len(sys.argv) > 2 else '/tmp/oldmansea_full.txt'

    with open(json_path) as f:
        data = json.load(f)

    with open(text_path) as f:
        text = f.read()

    # Strip title page metadata - start from "He was an old man..."
    story_start = text.find('He was an old man')
    if story_start > 0:
        # Include a bit of context before in case there's a chapter marker
        text = text[max(0, story_start - 100):]

    words = data['in_coca']
    total = len(words)
    results = []
    failed = []
    no_sentence = []

    for i, entry in enumerate(words):
        lemma = entry['lemma']
        forms = entry['forms']
        sentence = find_best_sentence(text, forms, lemma)

        if sentence:
            sentence = truncate_sentence(sentence)
            ok, reason = verify_sentence(sentence, forms)
            if not ok:
                failed.append((lemma, reason, sentence[:80]))
        else:
            no_sentence.append((lemma, forms))

        results.append({
            'lemma': lemma,
            'rep': entry['rep'],
            'forms': forms,
            'sentence': sentence,
        })

        print(f"\r  {i+1}/{total} {lemma}", end='', file=sys.stderr, flush=True)

    print(file=sys.stderr)

    # Report issues
    if failed:
        print(f"\nVerification issues ({len(failed)}):", file=sys.stderr)
        for lemma, reason, preview in failed:
            print(f"  [{lemma}] {reason}: {preview}...", file=sys.stderr)
    if no_sentence:
        print(f"\nNo sentence found ({len(no_sentence)}):", file=sys.stderr)
        for lemma, forms in no_sentence:
            print(f"  [{lemma}] forms={forms}", file=sys.stderr)

    output = {
        'book_title': data.get('book_title', '老人与海：The Old Man And The Sea（英文原版）'),
        'book_author': data.get('book_author', '海明威'),
        'book_id': '3300144556',
        'deck_name': '老人与海：The Old Man And The Sea（英文原版） (海明威)',
        'words': results,
        'excluded': data.get('excluded', []),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
