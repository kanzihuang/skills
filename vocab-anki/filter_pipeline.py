"""Combined filter pipeline: lemmatize → Anki dedup → COCA check.

Replaces the three-step (1d → 1e → 1f) workflow with a single Python invocation.
Reads WeRead bookmarklist API JSON from stdin, processes everything in-process,
and outputs final filtered results.

Usage:
    curl ... | python filter_pipeline.py [--anki <bookId>] [--book-id <bookId>]

Output sections:
    SUMMARY: X highlights → Y lemmas → A in Anki → B excluded → C final
    ---IN_COCA---
    lemma\trep\tforms
    ---EXCLUDED---
    lemma\trep\treason
"""

import json
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from utils import lemmatize_word
from coca_lookup import load_coca, in_coca


def query_anki_existing(book_id: str) -> set[str]:
    """Query AnkiConnect for existing WordIds matching the given bookId.
    Returns set of lemmas already in the deck."""
    try:
        import requests
        # Find notes matching the bookId pattern in WordId field
        resp = requests.post(
            "http://localhost:8765",
            json={
                "action": "findNotes",
                "version": 6,
                "params": {"query": f'"Vocabulary Card (WeRead)" WordId:*_{book_id}'}
            },
            timeout=5,
        )
        if resp.status_code != 200:
            return set()

        result = resp.json()
        if result.get("error"):
            return set()

        note_ids = result.get("result", [])
        if not note_ids:
            return set()

        # Fetch WordId field for found notes
        resp2 = requests.post(
            "http://localhost:8765",
            json={
                "action": "notesInfo",
                "version": 6,
                "params": {"notes": note_ids}
            },
            timeout=10,
        )
        if resp2.status_code != 200:
            return set()

        result2 = resp2.json()
        lemmas = set()
        for note in result2.get("result", []):
            word_id = note.get("fields", {}).get("WordId", {}).get("value", "")
            if word_id and "_" in word_id:
                lemma = word_id.rsplit("_", 1)[0]
                lemmas.add(lemma.lower())
        return lemmas

    except Exception:
        return set()


def query_meta_excluded(book_id: str) -> set[str]:
    """Read meta manifest card for previously excluded words."""
    try:
        import requests
        resp = requests.post(
            "http://localhost:8765",
            json={
                "action": "findNotes",
                "version": 6,
                "params": {"query": f'"Vocabulary Card (WeRead)" WordId:__META__{book_id}'}
            },
            timeout=5,
        )
        if resp.status_code != 200:
            return set()
        result = resp.json()
        if result.get("error") or not result.get("result"):
            return set()

        note_ids = result["result"]
        resp2 = requests.post(
            "http://localhost:8765",
            json={
                "action": "notesInfo",
                "version": 6,
                "params": {"notes": note_ids}
            },
            timeout=5,
        )
        if resp2.status_code != 200:
            return set()

        notes = resp2.json().get("result", [])
        if notes:
            excluded_field = notes[0].get("fields", {}).get("Excluded", {}).get("value", "")
            if excluded_field:
                return set(w.strip().lower() for w in excluded_field.split(",") if w.strip())
    except Exception:
        pass
    return set()


def main():
    # Parse args
    anki_book_id: Optional[str] = None
    book_id: Optional[str] = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--anki" and i + 1 < len(args):
            anki_book_id = args[i + 1]
            i += 2
        elif args[i] == "--book-id" and i + 1 < len(args):
            book_id = args[i + 1]
            i += 2
        else:
            i += 1

    # Read bookmarklist JSON from stdin
    data = json.load(sys.stdin)

    # Validate API response
    if "updated" not in data:
        err_info = data.get("errmsg", "") or data.get("error", "") or f"keys: {list(data.keys())}"
        print(f'ERROR: API response missing "updated" field — '
              f'possible auth failure or bad bookId. Response hint: {err_info}',
              file=sys.stderr)
        sys.exit(1)

    # Step 1d: Extract, filter, lemmatize
    marks = [h.get("markText", "").strip() for h in data.get("updated", [])]
    words_raw = [m for m in marks if m and " " not in m and not m.isdigit() and len(m) > 1]
    lemma_map: dict[str, list[str]] = {}
    for w in words_raw:
        lemma = lemmatize_word(w)
        if lemma not in lemma_map:
            lemma_map[lemma] = []
        lemma_map[lemma].append(w)

    all_lemmas = sorted(lemma_map.keys())
    n_highlights = len(marks)
    n_lemmas = len(all_lemmas)

    # Step 1e: Anki dedup (if book_id provided)
    anki_lemmas: set[str] = set()
    meta_excluded: set[str] = set()
    if anki_book_id:
        meta_excluded = query_meta_excluded(anki_book_id)
        anki_lemmas = query_anki_existing(anki_book_id)
        anki_lemmas |= meta_excluded  # meta excluded words are also considered "already handled"

    lemmas_after_anki = [l for l in all_lemmas if l.lower() not in anki_lemmas]
    n_anki = len(all_lemmas) - len(lemmas_after_anki)

    # Step 1f: COCA check
    coca_set = load_coca()
    passed = []
    rejected = []
    for lemma in lemmas_after_anki:
        forms = lemma_map[lemma]
        rep = min(forms, key=lambda x: (x[0].isupper(), len(x)))
        ok, detail = in_coca(lemma, coca_set)
        if ok:
            passed.append((lemma, rep, forms))
        else:
            reason = "不在 COCA 20000 中"
            if meta_excluded and lemma.lower() in meta_excluded:
                reason = "历史排除 (meta manifest)"
            rejected.append((lemma, rep, reason))

    n_coca_excluded = len(rejected)
    n_final = len(passed)

    # Output
    print(f"SUMMARY: {n_highlights} highlights → {n_lemmas} lemmas → "
          f"{n_anki} in Anki → {n_coca_excluded} excluded → {n_final} final")
    print("---IN_COCA---")
    for lemma, rep, forms in passed:
        print(f"{lemma}\t{rep}\t{','.join(forms)}")
    print("---EXCLUDED---")
    for lemma, rep, reason in rejected:
        print(f"{lemma}\t{rep}\t{reason}")

    # Print Anki-skipped words for reference
    if anki_lemmas:
        anki_skipped = [l for l in all_lemmas if l.lower() in anki_lemmas]
        print("---ANKI_SKIPPED---")
        for lemma in sorted(anki_skipped):
            forms = lemma_map[lemma]
            rep = min(forms, key=lambda x: (x[0].isupper(), len(x)))
            print(f"{lemma}\t{rep}\t{','.join(forms)}")


if __name__ == "__main__":
    main()
