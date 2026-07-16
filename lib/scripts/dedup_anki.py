#!/usr/bin/env python3
"""Mechanical Anki dedup by (sentence, word).  Runs after Step 2A, before Step 2B.

Queries Anki for existing cards matching the same (sentence, word) key.
Entries already in the deck are **removed from the JSON** — subsequent
steps (translation, definitions, sync) only see new words.

Does NOT depend on POS or lemma — only on sentence text and the surface form
of the target word.  Both are stable across POS corrections and lemma changes.

Usage::

    python dedup_anki.py /tmp/vocab-book-matched.json
"""

from __future__ import annotations

import json
import os
import re
import sys

# ── path setup ──────────────────────────────────────────────────────────────
_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

from lib.ankiconnect import AnkiConnect, AnkiConnectError  # noqa: E402

# ── regex ────────────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r'</?b>')
_TARGET_RE = re.compile(r'<b>(.*?)</b>')


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <matched.json>", file=sys.stderr)
        sys.exit(2)

    input_path = sys.argv[1]
    data = json.load(open(input_path, encoding='utf-8'))
    suffix = data.get('suffix', '')
    words = data.get('words', [])

    if not suffix:
        print("FATAL: missing 'suffix' in input JSON", file=sys.stderr)
        sys.exit(1)
    if not words:
        print("No words to dedup — empty batch.")
        return

    # ── query Anki for existing cards with this suffix ───────────────────
    try:
        ac = AnkiConnect()
        note_ids = ac.find_notes(
            f'note:"Vocabulary Card (WeRead)" WordId:*_{suffix}'
        )
    except AnkiConnectError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    # ── build (sentence, word) set from existing cards ───────────────────
    existing: set[tuple[str, str]] = set()
    if note_ids:
        for note in ac.notes_info(note_ids):
            sent_raw = note.get('fields', {}).get('Sentence', {}).get('value', '')
            if not sent_raw:
                continue
            sent = _TAG_RE.sub('', sent_raw).strip()
            m = _TARGET_RE.search(sent_raw)
            word = m.group(1) if m else ''
            if sent and word:
                existing.add((sent, word))

    # ── remove duplicates from JSON ──────────────────────────────────────
    n_existing = 0
    new_words = []
    for w in words:
        key = (w['sentence'].strip(), w['word'])
        if key in existing:
            n_existing += 1
        else:
            new_words.append(w)
    data['words'] = new_words

    # ── write back ───────────────────────────────────────────────────────
    json.dump(data, open(input_path, 'w', encoding='utf-8'),
              indent=2, ensure_ascii=False)
    print(f"Anki dedup: {n_existing} in deck (removed), {len(new_words)} new")


if __name__ == '__main__':
    main()
