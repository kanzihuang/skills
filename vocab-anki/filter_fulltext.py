#!/usr/bin/env python3
"""Full-text vocabulary filtering pipeline for vocab-anki.

Reads raw book text from stdin, performs comprehensive lemmatization, optional
chapter segmentation, COCA frequency-range filtering, and Anki dedup.  Outputs
the same JSON schema as filter_pipeline.py so sync_anki.py consumes it unchanged.

Usage
-----
    # Basic: all COCA words from full text
    cat book.txt | python filter_fulltext.py --json-out /tmp/out.json

    # With COCA frequency range (ranks 3001–10000 only)
    cat book.txt | python filter_fulltext.py --basic-range 3001-10000 --json-out /tmp/out.json

    # With chapter filtering (chapters 1–5 and 7)
    cat book.txt | python filter_fulltext.py \
        --chapter-titles '[{"chapterUid":1,"title":"Chapter 1"},...]' \
        --chapter-range "1-5,7" --json-out /tmp/out.json

    # Full pipeline with Anki dedup (new --anki-dedup flag)
    cat book.txt | python filter_fulltext.py \
        --basic-range 3001-10000 --chapter-range "1-5" \
        --chapter-titles '<json>' --anki-dedup same-book --book-id <bookId> \
        --json-out /tmp/out.json

    # Cross-deck dedup
    cat book.txt | python filter_fulltext.py \
        --anki-dedup all-decks --book-id <bookId> --json-out /tmp/out.json
"""

from __future__ import annotations

import json
import re
import sys
import os
from typing import Optional

# ── path setup ──────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.coca import load_coca, load_freq_ranked, in_coca             # noqa: E402
from lib.lemmatize import lemmatize, build_spacy_map               # noqa: E402


# ── Anki dedup helpers ──────────────────────────────────────────────────────

def _get_anki_connect():
    """Lazy-import AnkiConnect (only needed when --anki is used)."""
    from ankiconnect import AnkiConnect, AnkiConnectError
    return AnkiConnect, AnkiConnectError


def query_anki_existing(ac, book_id: str) -> set[str]:
    """Query AnkiConnect for existing WordIds matching the given bookId.

    Returns set of lemmas already in the deck (lowercased).
    """
    AnkiConnectError = _get_anki_connect()[1]
    try:
        note_ids = ac.find_notes_by_field("", "WordId", f"*_{book_id}")
        if not note_ids:
            return set()
        info = ac.notes_info(note_ids)
        lemmas: set[str] = set()
        for note in info:
            word_id = note.get("fields", {}).get("WordId", {}).get("value", "")
            if word_id and "_" in word_id:
                lemma = word_id.rsplit("_", 1)[0]
                lemmas.add(lemma.lower())
        return lemmas
    except AnkiConnectError as e:
        print(f"WARNING: AnkiConnect query failed for existing words: {e}", file=sys.stderr)
        return set()
    except Exception as e:
        print(f"WARNING: Unexpected error querying Anki existing words: {e}", file=sys.stderr)
        return set()







# ── chapter segmentation ────────────────────────────────────────────────────

def _strip_punct(s: str) -> str:
    """Remove all non-alphanumeric characters for fuzzy matching."""
    return re.sub(r'[^a-zA-Z0-9]', '', s)


def find_chapter_offsets(text: str, titles: list[dict]) -> list[dict]:
    """Locate WeRead chapter titles within the raw text.

    Args:
        text: Raw book text.
        titles: List of WeRead chapter objects, each with ``chapterUid`` and
                ``title``, **in reading order**.

    Returns:
        List of dicts ``{chapterUid, title, index, offset}`` sorted by offset.
        *index* is the 1-based flattened chapter number.  *offset* is the
        character position in *text*, or -1 if unmatched.
    """
    results: list[dict] = []
    for i, ch in enumerate(titles):
        title = ch.get("title", "")
        uid = ch.get("chapterUid", i)
        offset = -1

        # Strategy 1: exact substring
        offset = text.find(title)

        # Strategy 2: case-insensitive
        if offset == -1:
            offset = text.lower().find(title.lower())

        # Strategy 3: stripped (alphanumeric only), case-insensitive
        if offset == -1:
            stripped_title = _strip_punct(title)
            stripped_text = _strip_punct(text)
            # Only try if stripped_title is non-empty and reasonably long
            if len(stripped_title) >= 3:
                idx = stripped_text.find(stripped_title.lower())
                if idx != -1:
                    # Map back to original text offset (approximate)
                    # Walk through original text counting alphanumeric chars
                    alpha_count = 0
                    for j, ch_orig in enumerate(text):
                        if ch_orig.isalnum():
                            if alpha_count == idx:
                                offset = j
                                break
                            alpha_count += 1

        if offset == -1:
            print(f"WARNING: Chapter title not matched in text: '{title}'",
                  file=sys.stderr)

        results.append({
            "chapterUid": uid,
            "title": title,
            "index": i + 1,         # 1-based flat index
            "offset": offset,
        })

    return results


def parse_chapter_range(range_str: str, n_chapters: int) -> set[int]:
    """Parse a chapter range string like '1-5,7,10-12' into a set of 1-based indices.

    Args:
        range_str: User-supplied range string (e.g. ``"1-5,7,10-12"``).
        n_chapters: Total number of chapters (for bounds validation).

    Returns:
        Set of 1-based chapter indices to include.

    Raises:
        ValueError: If the range string is malformed or out of bounds.
    """
    if not range_str or not range_str.strip():
        return set(range(1, n_chapters + 1))

    selected: set[int] = set()
    parts = range_str.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_str, hi_str = part.split("-", 1)
            lo, hi = int(lo_str.strip()), int(hi_str.strip())
            if lo < 1 or hi > n_chapters:
                raise ValueError(
                    f"Chapter range {lo}-{hi} out of bounds (1–{n_chapters})")
            if lo > hi:
                raise ValueError(
                    f"Chapter range {lo}-{hi} is inverted (start > end)")
            for ch in range(lo, hi + 1):
                selected.add(ch)
        else:
            ch = int(part.strip())
            if ch < 1 or ch > n_chapters:
                raise ValueError(
                    f"Chapter {ch} out of bounds (1–{n_chapters})")
            selected.add(ch)
    return selected


def build_chapter_intervals(
    text: str, offsets: list[dict], selected: set[int],
) -> list[tuple[int, int, int, str]]:
    """Build (start, end, index, title) intervals for selected chapters.

    Only chapters that were successfully matched (offset >= 0) and are in
    *selected* are included.  Text between matched offsets is assigned to the
    preceding chapter.
    """
    # Sort matched chapters by offset
    matched = sorted(
        [o for o in offsets if o["offset"] >= 0],
        key=lambda x: x["offset"],
    )
    if not matched:
        return []

    intervals: list[tuple[int, int, int, str]] = []
    for i, m in enumerate(matched):
        if m["index"] not in selected:
            continue
        start = m["offset"]
        # End is the next matched chapter's offset, or end of text
        end = matched[i + 1]["offset"] if i + 1 < len(matched) else len(text)
        intervals.append((start, end, m["index"], m["title"]))

    return intervals


# ── main pipeline ───────────────────────────────────────────────────────────

def main() -> None:
    # -- parse CLI args -------------------------------------------------------
    basic_min: int = 0
    basic_max: int = 0
    chapter_range_str: Optional[str] = None
    chapter_titles_json: Optional[str] = None
    book_id: Optional[str] = None
    json_out_path: Optional[str] = None
    anki_dedup: str = ""               # "" | "same-book" | "all-decks"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--basic-range" and i + 1 < len(args):
            parts = args[i + 1].split("-")
            if len(parts) == 2:
                basic_min = int(parts[0])
                basic_max = int(parts[1])
            i += 2
        elif args[i] == "--chapter-range" and i + 1 < len(args):
            chapter_range_str = args[i + 1]
            i += 2
        elif args[i] == "--chapter-titles" and i + 1 < len(args):
            chapter_titles_json = args[i + 1]
            i += 2
        elif args[i] == "--anki-dedup" and i + 1 < len(args):
            anki_dedup = args[i + 1]
            if anki_dedup not in ("same-book", "all-decks"):
                print(f"ERROR: --anki-dedup must be 'same-book' or 'all-decks', got '{anki_dedup}'",
                      file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--book-id" and i + 1 < len(args):
            book_id = args[i + 1]
            i += 2
        elif args[i] == "--json-out" and i + 1 < len(args):
            json_out_path = args[i + 1]
            i += 2
        else:
            i += 1

    # -- read stdin -----------------------------------------------------------
    text = sys.stdin.read()
    if not text.strip():
        print("Error: no text provided on stdin", file=sys.stderr)
        sys.exit(1)

    coca_set = load_coca()

    # Build spaCy lemma map from full text (run once, POS-aware)
    spacy_map = build_spacy_map(text)

    # -- chapter segmentation (if requested) ----------------------------------
    # lemma_forms:  lemma → set of surface forms found in text
    # lemma_chapters: lemma → set of (chapter_index, chapter_title) tuples
    lemma_forms: dict[str, set[str]] = {}
    lemma_chapters: dict[str, set[tuple[int, str]]] = {}

    chapter_titles: list[dict] = []
    if chapter_titles_json:
        try:
            chapter_titles = json.loads(chapter_titles_json)
        except json.JSONDecodeError as e:
            print(f"Error: invalid --chapter-titles JSON: {e}", file=sys.stderr)
            sys.exit(1)

    if chapter_titles:
        offsets = find_chapter_offsets(text, chapter_titles)
        n_matched = sum(1 for o in offsets if o["offset"] >= 0)

        if n_matched == 0:
            print("WARNING: No chapter titles matched in text. "
                  "Processing entire text as one block.", file=sys.stderr)
            # Fall through to full-text processing below
        else:
            print(f"Chapter detection: {n_matched}/{len(chapter_titles)} titles matched.",
                  file=sys.stderr)

            selected_chapters: set[int]
            if chapter_range_str:
                try:
                    selected_chapters = parse_chapter_range(
                        chapter_range_str, len(chapter_titles))
                except ValueError as e:
                    print(f"Error: invalid --chapter-range: {e}", file=sys.stderr)
                    sys.exit(1)
            else:
                selected_chapters = set(range(1, len(chapter_titles) + 1))

            intervals = build_chapter_intervals(text, offsets, selected_chapters)

            if intervals:
                # Process each chapter segment
                for start, end, ch_idx, ch_title in intervals:
                    ch_text = text[start:end]
                    ch_words = set(re.findall(r"[a-zA-Z]{2,}", ch_text.lower()))
                    for w in ch_words:
                        lemma = lemmatize(w, coca_set, spacy_map)
                        if lemma not in lemma_forms:
                            lemma_forms[lemma] = set()
                            lemma_chapters[lemma] = set()
                        lemma_forms[lemma].add(w)
                        lemma_chapters[lemma].add((ch_idx, ch_title))
            else:
                print("WARNING: No chapter intervals matched the selection. "
                      "Processing entire text as one block.", file=sys.stderr)
                # Fall through to full-text processing below

    # If no chapter segmentation or it produced nothing, process full text
    if not lemma_forms:
        all_words = set(re.findall(r"[a-zA-Z]{2,}", text.lower()))
        for w in all_words:
            lemma = lemmatize(w, coca_set, spacy_map)
            if lemma not in lemma_forms:
                lemma_forms[lemma] = set()
                lemma_chapters[lemma] = set()
            lemma_forms[lemma].add(w)
            # No chapter info — use empty set

    total_raw_words = len(re.findall(r"[a-zA-Z]{2,}", text.lower()))
    total_lemmas = len(lemma_forms)

    # -- COCA frequency range filtering ---------------------------------------
    passed: list[tuple[str, str, list[str]]] = []      # (lemma, rep, forms)
    rejected: list[tuple[str, str, str]] = []           # (lemma, rep, reason)

    if basic_min > 0 or basic_max > 0:
        all_freq = load_freq_ranked()
        lo = max(basic_min, 1)
        hi = min(basic_max, len(all_freq)) if basic_max else len(all_freq)
        in_range_set: set[str] = set(all_freq[lo - 1:hi])

    for lemma in sorted(lemma_forms.keys()):
        forms = sorted(lemma_forms[lemma])
        rep = lemma  # rep is always the lemma in full-text mode

        # COCA membership check via in_coca() — handles derivational forms
        # that lemmatize() couldn't reduce (e.g. indulgently → indulgent)
        ok, detail = in_coca(lemma, coca_set)
        if not ok:
            rejected.append((lemma, rep, "不在 COCA 20000 中"))
            continue

        # Determine the canonical COCA word for frequency rank lookup.
        # in_coca() detail: "word" for direct match, "word -> base" for fallback.
        coca_word = lemma
        if " -> " in detail:
            coca_word = detail.split(" -> ", 1)[1]

        # COCA frequency range check (using canonical COCA word's rank)
        if basic_min > 0 or basic_max > 0:
            if coca_word not in in_range_set:
                try:
                    rank = all_freq.index(coca_word) + 1
                except ValueError:
                    rank = 0
                rejected.append((lemma, rep, f"COCA 词频范围外 (rank {rank})"))
                continue

        passed.append((lemma, rep, forms))

    n_coca_excluded = len(rejected)
    lemmas_before_anki = len(passed)

    # -- Anki dedup -----------------------------------------------------------
    anki_cards: set[str] = set()
    if anki_dedup:
        AnkiConnect, _AnkiConnectError = _get_anki_connect()
        try:
            ac = AnkiConnect()

            if anki_dedup == "all-decks":
                anki_cards = ac.query_anki_all_lemmas()
            else:
                if not book_id:
                    print("WARNING: --anki-dedup same-book requires --book-id, skipping Anki dedup",
                          file=sys.stderr)
                else:
                    anki_cards = query_anki_existing(ac, book_id)
        except Exception as e:
            print(f"WARNING: AnkiConnect unreachable, skipping Anki dedup: {e}",
                  file=sys.stderr)

    # Helper: check both lemma AND surface forms against handled set.
    # Catches derivational adjectives where WordId uses surface form
    # (e.g. Anki has blundering_3300144556, lemma is blunder).
    def _lemma_handled(lemma: str, forms: list[str], handled: set[str]) -> bool:
        if lemma.lower() in handled:
            return True
        for f in forms:
            if f.lower() in handled:
                return True
        return False

    if anki_cards:
        n_before = len(passed)
        passed = [
            (lemma, rep, forms) for lemma, rep, forms in passed
            if not _lemma_handled(lemma, forms, anki_cards)
        ]
        n_anki_filtered = n_before - len(passed)
    else:
        n_anki_filtered = 0

    n_final = len(passed)

    # -- stdout output (human-readable) ---------------------------------------
    parts = [
        f"Raw tokens: {total_raw_words}",
        f"Unique lemmas: {total_lemmas}",
    ]
    if basic_min or basic_max:
        parts.append(f"COCA range: {basic_min}-{basic_max}")
    parts.append(f"COCA excluded: {n_coca_excluded}")
    if n_anki_filtered:
        parts.append(f"Anki filtered: {n_anki_filtered}")
    parts.append(f"Final: {n_final}")
    print(f"SUMMARY: {' | '.join(parts)}")

    print("---IN_COCA---")
    for lemma, rep, forms in passed:
        print(f"{lemma}\t{rep}\t{','.join(forms)}")
    print("---EXCLUDED---")
    for lemma, rep, reason in rejected:
        print(f"{lemma}\t{rep}\t{reason}")

    # -- JSON output ----------------------------------------------------------
    if json_out_path:
        json_out = {
            "summary": {
                "total_words": total_raw_words,
                "lemmas": total_lemmas,
                "in_anki": n_anki_filtered,
                "coca_excluded": n_coca_excluded,
                "final": n_final,
            },
            "in_coca": [
                {
                    "lemma": lemma,
                    "rep": rep,
                    "forms": forms,
                    "chapters": sorted(
                        [
                            {"chapterUid": idx, "chapterTitle": title}
                            for idx, title in lemma_chapters.get(lemma, set())
                        ],
                        key=lambda x: x["chapterUid"],
                    ),
                }
                for lemma, rep, forms in passed
            ],
            "excluded": [
                {"lemma": lemma, "rep": rep, "reason": reason}
                for lemma, rep, reason in rejected
            ],
        }
        with open(json_out_path, "w", encoding="utf-8") as f:
            json.dump(json_out, f, ensure_ascii=False, indent=2)

    # Summary line for Claude
    print(f"\nDone. {n_final} words → {json_out_path}" if json_out_path
          else f"\nDone. {n_final} words ready.")


if __name__ == "__main__":
    main()
