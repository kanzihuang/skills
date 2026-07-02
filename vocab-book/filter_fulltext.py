#!/usr/bin/env python3
"""Full-text vocabulary filtering pipeline for vocab-book.

Reads raw book text from stdin, performs comprehensive lemmatization, COCA
frequency-range filtering, and COCA level annotation.  Outputs structured JSON
consumed by sync_anki.py.

Does NOT depend on WeRead (微信读书).  Does NOT connect to AnkiConnect.
Generates a UUID suffix for WordId/audio namespace isolation.

Usage
-----
    # Basic: all COCA words from full text
    cat book.txt | python filter_fulltext.py --json-out /tmp/out.json

    # With BNC/COCA word family level range (levels 3-10 only)
    cat book.txt | python filter_fulltext.py --basic-range 3-10 --json-out /tmp/out.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from typing import Optional

# ── path setup ──────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.coca import (load_coca, in_coca,                         # noqa: E402
                         get_word_level, load_level_range)
from lib.lemmatize import lemmatize, build_spacy_map               # noqa: E402


# ── main pipeline ───────────────────────────────────────────────────────────

def main() -> None:
    # -- parse CLI args -------------------------------------------------------
    basic_min: int = 0
    basic_max: int = 0
    json_out_path: Optional[str] = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--basic-range" and i + 1 < len(args):
            parts = args[i + 1].split("-")
            if len(parts) == 2:
                basic_min = int(parts[0])
                basic_max = int(parts[1])
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

    # Generate UUID suffix for WordId/audio namespace isolation
    suffix = uuid.uuid4().hex[:12]

    # -- tokenize & lemmatize -------------------------------------------------
    # lemma_forms:  lemma → set of surface forms found in text
    lemma_forms: dict[str, set[str]] = {}

    all_words = set(re.findall(r"[a-zA-Z]{2,}", text.lower()))
    for w in all_words:
        lemma = lemmatize(w, coca_set, spacy_map)
        if lemma not in lemma_forms:
            lemma_forms[lemma] = set()
        lemma_forms[lemma].add(w)

    total_raw_words = len(re.findall(r"[a-zA-Z]{2,}", text.lower()))
    total_lemmas = len(lemma_forms)

    # -- COCA frequency range filtering ---------------------------------------
    passed: list[tuple[str, str, list[str]]] = []       # (lemma, rep, forms)
    rejected: list[tuple[str, str, str]] = []            # (lemma, rep, reason)

    if basic_min > 0 or basic_max > 0:
        lo = max(basic_min, 1)
        hi = min(basic_max, 25) if basic_max else 25
        in_range_set = load_level_range(lo, hi)

    passed_coca_levels: dict[str, int | None] = {}

    for lemma in sorted(lemma_forms.keys()):
        forms = sorted(lemma_forms[lemma])
        rep = lemma  # rep is always the lemma in full-text mode

        # COCA membership check via in_coca() — handles derivational forms
        # that lemmatize() couldn't reduce (e.g. indulgently → indulgent)
        ok, detail = in_coca(lemma, coca_set)
        if not ok:
            rejected.append((lemma, rep, "不在 BNC/COCA 25000 词族中"))
            continue

        # Determine the canonical COCA word for frequency rank lookup.
        # in_coca() detail: "word" for direct match, "word -> base" for fallback.
        coca_word = lemma
        if " -> " in detail:
            coca_word = detail.split(" -> ", 1)[1]

        # Always resolve COCA level for banding in sync_anki.py
        passed_coca_levels[lemma] = get_word_level(coca_word)

        # COCA frequency range check (using canonical COCA word's rank)
        if basic_min > 0 or basic_max > 0:
            if coca_word not in in_range_set:
                lvl = passed_coca_levels[lemma]
                lvl_str = f"level {lvl}/25" if lvl else "不在词族中"
                rejected.append((lemma, rep, f"BNC/COCA 词族等级范围外 ({lvl_str})"))
                continue

        passed.append((lemma, rep, forms))

    n_coca_excluded = len(rejected)
    n_final = len(passed)

    # -- stdout output (human-readable) ---------------------------------------
    parts = [
        f"Raw tokens: {total_raw_words}",
        f"Unique lemmas: {total_lemmas}",
    ]
    if basic_min or basic_max:
        parts.append(f"BNC/COCA levels: {basic_min}-{basic_max}")
    parts.append(f"COCA excluded: {n_coca_excluded}")
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
            "suffix": suffix,
            "summary": {
                "total_words": total_raw_words,
                "lemmas": total_lemmas,
                "coca_excluded": n_coca_excluded,
                "final": n_final,
            },
            "in_coca": [
                {
                    "lemma": lemma,
                    "rep": rep,
                    "forms": forms,
                    "coca_level": passed_coca_levels.get(lemma),
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
