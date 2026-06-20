"""Combined filter pipeline: lemmatize → Anki dedup → COCA check.

Replaces the three-step (1d → 1e → 1f) workflow with a single Python invocation.
Reads WeRead bookmarklist API JSON from stdin, processes everything in-process,
and outputs final filtered results.

Usage:
    curl ... | python filter_pipeline.py [--anki <bookId>] [--book-id <bookId>] [--json-out <path>]

Output sections:
    SUMMARY: X highlights → Y lemmas → A in Anki → B excluded → C final
    ---IN_COCA---
    lemma\trep\tforms
    ---EXCLUDED---
    lemma\trep\treason
"""

import json
import re
import sys
import os
from typing import Optional

# Characters stripped from word boundaries — sentence-boundary punctuation
# that can never be part of an English word. Excludes apostrophe (contractions
# like don't) and hyphen (compounds like well-known).
_PUNCT_STRIP = '.,;:!?()[]{}«»"\'""''…—–、。，；：！？』『「」 \t\n\r\v'


def clean_mark(text: str) -> str:
    """Strip surrounding punctuation and whitespace from a highlight mark.

    Users often highlight a word plus trailing period/comma/quote.
    This removes those artifacts while preserving internal punctuation
    (apostrophes in contractions, hyphens in compounds).
    """
    return text.strip(_PUNCT_STRIP)


def pick_rep(forms: list[str]) -> str:
    """Pick the best surface form for display: shortest lowercase form.

    Prefers lowercase over capitalized (e.g. "clad" over "Clad"),
    normalizes to lowercase unless the word is an all-caps acronym.
    """
    # Pick shortest form preferring lowercase first-char over uppercase
    best = None
    for f in forms:
        if best is None:
            best = f
        elif f[0].isupper() and not best[0].isupper():
            continue  # lowercase best beats uppercase f
        elif not f[0].isupper() and best[0].isupper():
            best = f  # lowercase f beats uppercase best
        elif len(f) < len(best):
            best = f  # same case class, pick shorter
    if best and not best.isupper():
        best = best.lower()
    return best or forms[0].lower()

sys.path.insert(0, os.path.dirname(__file__))
from utils import lemmatize_word
from coca_lookup import load_coca, in_coca
from ankiconnect import AnkiConnect, AnkiConnectError


def query_anki_existing(ac: AnkiConnect, book_id: str) -> set[str]:
    """Query AnkiConnect for existing WordIds matching the given bookId.
    Returns set of lemmas already in the deck."""
    try:
        note_ids = ac.find_notes_by_field(
            "",  # search all decks
            "WordId",
            f"*_{book_id}",
        )
        if not note_ids:
            return set()

        # Fetch WordId field for found notes
        info = ac.notes_info(note_ids)
        lemmas = set()
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


def query_meta_excluded(ac: AnkiConnect, book_id: str) -> set[str]:
    """Read meta manifest card for previously excluded words from Sentence field JSON.

    The 'Excluded' field was never a real note-type field in 'Vocabulary Card (WeRead)';
    AnkiConnect silently drops writes to non-existent fields. The actual excluded words
    live in the Sentence field as a JSON manifest under the 'excluded' key.
    """
    try:
        meta_word_id = f"__META__{book_id}"
        note_ids = ac.find_notes_by_field("", "WordId", meta_word_id)
        if not note_ids:
            return set()

        info = ac.notes_info(note_ids[:1])
        if not info:
            return set()

        sentence_field = info[0].get("fields", {}).get("Sentence", {}).get("value", "")
        if not sentence_field:
            return set()

        manifest = json.loads(sentence_field)
        if manifest.get("type") != "vocab-anki-meta":
            return set()

        excluded_value = manifest.get("excluded", [])
        return {word.lower() for word in excluded_value}
    except AnkiConnectError as e:
        print(f"WARNING: AnkiConnect query failed for meta manifest: {e}", file=sys.stderr)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"WARNING: Failed to parse meta manifest JSON: {e}", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Unexpected error querying meta manifest: {e}", file=sys.stderr)
    return set()


def main():
    # Parse args
    anki_book_id: Optional[str] = None
    book_id: Optional[str] = None
    json_out_path: Optional[str] = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--anki" and i + 1 < len(args):
            anki_book_id = args[i + 1]
            i += 2
        elif args[i] == "--book-id" and i + 1 < len(args):
            book_id = args[i + 1]
            i += 2
        elif args[i] == "--json-out" and i + 1 < len(args):
            json_out_path = args[i + 1]
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
    # clean_mark strips sentence-boundary punctuation (e.g. "vexed." → "vexed")
    #
    # Also extract chapter info: each highlight has a chapterUid; chapters[]
    # maps chapterUid → title. We preserve this so Step 3.0 can narrow
    # sentence-matching to the chapter the word was highlighted in.
    chapters_raw = data.get("chapters", [])
    chapter_map: dict[int, str] = {}
    for ch in chapters_raw:
        uid = ch.get("chapterUid")
        title = ch.get("title", "")
        if uid is not None:
            chapter_map[uid] = title

    highlights = data.get("updated", [])
    marks = [clean_mark(h.get("markText", "")) for h in highlights]
    words_raw = [m for m in marks if m and " " not in m and not m.isdigit() and len(m) > 1]

    # Build a mapping from markText → list of chapterUids (one word may be
    # highlighted in multiple chapters).  ChapterUid may be absent (None)
    # for highlights without chapter context; treat as "unknown".
    mark_chapters: dict[str, list[int | None]] = {}
    for h in highlights:
        mt = clean_mark(h.get("markText", ""))
        if not mt or mt not in words_raw:
            continue
        ch_uid = h.get("chapterUid")
        if mt not in mark_chapters:
            mark_chapters[mt] = []
        mark_chapters[mt].append(ch_uid if ch_uid in chapter_map else None)

    lemma_map: dict[str, list[str]] = {}
    lemma_chapters: dict[str, set[int | None]] = {}  # lemma → set of chapterUids
    for w in words_raw:
        lemma = lemmatize_word(w)
        if lemma not in lemma_map:
            lemma_map[lemma] = []
            lemma_chapters[lemma] = set()
        lemma_map[lemma].append(w)
        for ch_uid in mark_chapters.get(w, [None]):
            lemma_chapters[lemma].add(ch_uid)

    all_lemmas = sorted(lemma_map.keys())
    n_highlights = len(marks)
    n_lemmas = len(all_lemmas)

    # Step 1e: Anki dedup (if book_id provided)
    ac = AnkiConnect() if anki_book_id else None
    anki_cards: set[str] = set()        # lemmas with actual Anki word cards
    meta_excluded: set[str] = set()     # lemmas previously excluded (from meta manifest)
    anki_all_handled: set[str] = set()  # union of both — used for dedup
    if ac and anki_book_id:
        meta_excluded = query_meta_excluded(ac, anki_book_id)
        anki_cards = query_anki_existing(ac, anki_book_id)
        anki_all_handled = anki_cards | meta_excluded

    lemmas_after_anki = [l for l in all_lemmas if l.lower() not in anki_all_handled]
    n_anki_cards = sum(1 for l in all_lemmas if l.lower() in anki_cards)
    n_meta = sum(1 for l in all_lemmas if l.lower() in meta_excluded and l.lower() not in anki_cards)
    n_anki_total = n_anki_cards + n_meta

    # Step 1f: COCA check
    coca_set = load_coca()
    passed = []
    rejected = []
    for lemma in lemmas_after_anki:
        forms = lemma_map[lemma]
        rep = pick_rep(forms)
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

    # --- stdout output (human-readable, for Claude to parse) ---
    print(f"SUMMARY: {n_highlights} highlights → {n_lemmas} lemmas → "
          f"{n_anki_cards} in Anki, {n_meta} excluded → "
          f"{n_coca_excluded} new COCA excluded → {n_final} final")
    print("---IN_COCA---")
    for lemma, rep, forms in passed:
        print(f"{lemma}\t{rep}\t{','.join(forms)}")
    print("---EXCLUDED---")
    for lemma, rep, reason in rejected:
        print(f"{lemma}\t{rep}\t{reason}")

    # Print Anki-skipped words for reference (split by source)
    if anki_all_handled:
        anki_skipped_cards = [l for l in all_lemmas if l.lower() in anki_cards]
        anki_skipped_meta = [l for l in all_lemmas if l.lower() in meta_excluded and l.lower() not in anki_cards]
        if anki_skipped_cards:
            print("---ANKI_SKIPPED---")
            for lemma in sorted(anki_skipped_cards):
                forms = lemma_map[lemma]
                rep = pick_rep(forms)
                print(f"{lemma}\t{rep}\t{','.join(forms)}")
        if anki_skipped_meta:
            print("---META_EXCLUDED---")
            for lemma in sorted(anki_skipped_meta):
                forms = lemma_map[lemma]
                rep = pick_rep(forms)
                print(f"{lemma}\t{rep}\t{','.join(forms)}")

    # --- JSON output (structured, for Claude to avoid manual transcription) ---
    if json_out_path:
        json_out = {
            "summary": {
                "highlights": n_highlights,
                "lemmas": n_lemmas,
                "in_anki": n_anki_cards,
                "meta_excluded": n_meta,
                "coca_excluded": n_coca_excluded,
                "final": n_final,
            },
            "in_coca": [
                {
                    "lemma": lemma, "rep": rep, "forms": forms,
                    "chapters": sorted([
                        {"chapterUid": uid, "chapterTitle": chapter_map.get(uid, "")}
                        for uid in lemma_chapters.get(lemma, set()) if uid is not None
                    ], key=lambda x: x["chapterUid"]),
                }
                for lemma, rep, forms in passed
            ],
            "excluded": [
                {"lemma": lemma, "rep": rep, "reason": reason}
                for lemma, rep, reason in rejected
            ],
        }
        if anki_all_handled:
            anki_skipped_json = []
            for l in sorted(anki_cards):
                if l.startswith("__") or l not in lemma_map:
                    continue  # skip meta entries + stale excluded words no longer in highlights
                anki_skipped_json.append({
                    "lemma": l,
                    "rep": pick_rep(lemma_map[l]),
                    "forms": lemma_map[l],
                })
            if anki_skipped_json:
                json_out["anki_skipped"] = anki_skipped_json
        if meta_excluded:
            meta_excluded_json = []
            for l in sorted(meta_excluded):
                if l not in lemma_map:
                    continue  # stale meta entries no longer in current highlights
                meta_excluded_json.append({
                    "lemma": l,
                    "rep": pick_rep(lemma_map[l]),
                    "forms": lemma_map[l],
                })
            if meta_excluded_json:
                json_out["meta_excluded"] = meta_excluded_json
        with open(json_out_path, "w", encoding="utf-8") as f:
            json.dump(json_out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
