#!/usr/bin/env python3
"""Full-text vocabulary filtering pipeline for vocab-book.

Reads raw book text from stdin, tokenizes with spaCy, and filters unique
surface forms against BNC/COCA word families.  No lemmatization — the
authoritative lemma is determined later by match_sentences.py from the
specific sentence context.

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


# ── main pipeline ───────────────────────────────────────────────────────────

def _check_spacy() -> bool:
    """Verify spaCy + model are functional.  Try auto-repair if broken."""
    try:
        import spacy  # noqa: F401
    except ImportError:
        print("Error: spaCy not installed. Run: pip install spacy", file=sys.stderr)
        return False

    try:
        spacy.load("en_core_web_sm")
        return True
    except Exception:
        pass

    # Model missing or dependency broken — try auto-repair
    print("[warn] spaCy model/dependency missing, attempting auto-repair...", file=sys.stderr)
    import subprocess
    venv_python = sys.executable

    # 1. Install click (common missing dep that breaks spacy import)
    try:
        subprocess.run(
            [venv_python, "-m", "pip", "install", "-q", "click"],
            check=True, capture_output=True, timeout=60,
        )
    except Exception:
        pass

    # 2. Download model
    try:
        subprocess.run(
            [venv_python, "-m", "spacy", "download", "en_core_web_sm"],
            check=True, capture_output=True, timeout=120,
        )
    except Exception:
        pass

    # Final check
    try:
        spacy.load("en_core_web_sm")
        print("[ok] spaCy auto-repair succeeded", file=sys.stderr)
        return True
    except Exception as e:
        print(f"FATAL: spaCy still broken after repair attempt: {e}", file=sys.stderr)
        print("Cannot continue — POS-aware lemmatization is required.", file=sys.stderr)
        return False


def main() -> None:
    # -- parse CLI args -------------------------------------------------------
    basic_min: int = 0
    basic_max: int = 0
    json_out_path: Optional[str] = None
    book_title: Optional[str] = None
    book_author: Optional[str] = None

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
        elif args[i] == "--book-title" and i + 1 < len(args):
            book_title = args[i + 1]
            i += 2
        elif args[i] == "--book-author" and i + 1 < len(args):
            book_author = args[i + 1]
            i += 2
        else:
            i += 1

    # -- pre-flight: verify spaCy is functional --------------------------------
    if not _check_spacy():
        sys.exit(1)

    # -- read stdin -----------------------------------------------------------
    text = sys.stdin.read()
    if not text.strip():
        print("Error: no text provided on stdin", file=sys.stderr)
        sys.exit(1)

    coca_set = load_coca()

    # Generate UUID suffix for WordId/audio namespace isolation
    suffix = uuid.uuid4().hex[:12]

    # ── tokenize & COCA filter ────────────────────────────────────────────
    # Filter is surface-form-only: each unique surface form is checked against
    # the COCA word families directly. No lemmatization — the authoritative
    # lemma is determined later by match_sentences.py from the specific sentence.
    import spacy

    nlp = spacy.load("en_core_web_sm")

    surface_forms: set[str] = set()
    raw_token_count = 0

    chunk_size = 100_000
    for i in range(0, len(text), chunk_size):
        doc = nlp(text[i:i + chunk_size])
        for token in doc:
            if not token.is_alpha or len(token.text) < 2:
                continue
            raw_token_count += 1
            surface_forms.add(token.text.lower())

    total_raw_words = raw_token_count
    total_unique = len(surface_forms)

    # -- COCA frequency range filtering ---------------------------------------
    passed: list[tuple[str, str, list[str]]] = []       # (surface, rep, forms)
    rejected: list[tuple[str, str, str]] = []            # (surface, rep, reason)

    if basic_min > 0 or basic_max > 0:
        lo = max(basic_min, 1)
        hi = min(basic_max, 25) if basic_max else 25
        in_range_set = load_level_range(lo, hi)

    passed_coca_levels: dict[str, int | None] = {}

    for surface in sorted(surface_forms):
        rep = surface

        # COCA membership: check surface form directly against word families
        ok, detail = in_coca(surface, coca_set)
        if not ok:
            rejected.append((surface, rep, "不在 BNC/COCA 25000 词族中"))
            continue

        # Determine the canonical COCA word for frequency rank lookup
        coca_word = surface
        if " -> " in detail:
            coca_word = detail.split(" -> ", 1)[1]

        # Always resolve COCA level for banding in sync_anki.py
        passed_coca_levels[surface] = get_word_level(coca_word)

        # COCA frequency range check
        if basic_min > 0 or basic_max > 0:
            if coca_word not in in_range_set:
                lvl = passed_coca_levels[surface]
                lvl_str = f"level {lvl}/25" if lvl else "不在词族中"
                rejected.append((surface, rep, f"BNC/COCA 词族等级范围外 ({lvl_str})"))
                continue

        passed.append((surface, rep, [surface]))

    n_coca_excluded = len(rejected)
    n_final = len(passed)

    # -- stdout output (human-readable) ---------------------------------------
    parts = [
        f"Raw tokens: {total_raw_words}",
        f"Unique surfaces: {total_unique}",
    ]
    if basic_min or basic_max:
        parts.append(f"BNC/COCA levels: {basic_min}-{basic_max}")
    parts.append(f"COCA excluded: {n_coca_excluded}")
    parts.append(f"Final: {n_final}")
    print(f"SUMMARY: {' | '.join(parts)}")

    print("---IN_COCA---")
    for surface, rep, forms in passed:
        print(f"{surface}\t{rep}\t{','.join(forms)}")
    print("---EXCLUDED---")
    for surface, rep, reason in rejected:
        print(f"{surface}\t{rep}\t{reason}")

    # -- JSON output ----------------------------------------------------------
    if json_out_path:
        json_out = {
            "book_title": book_title or "",
            "book_author": book_author or "",
            "suffix": suffix,
            "summary": {
                "total_words": total_raw_words,
                "unique_surfaces": total_unique,
                "coca_excluded": n_coca_excluded,
                "final": n_final,
            },
            "in_coca": [
                {
                    "lemma": surface,
                    "rep": rep,
                    "forms": [surface],
                    "coca_level": passed_coca_levels.get(surface),
                }
                for surface, rep, forms in passed
            ],
            "excluded": [
                {"lemma": surface, "rep": rep, "reason": reason}
                for surface, rep, reason in rejected
            ],
        }
        with open(json_out_path, "w", encoding="utf-8") as f:
            json.dump(json_out, f, ensure_ascii=False, indent=2)

    # Summary line for Claude
    print(f"\nDone. {n_final} words → {json_out_path}" if json_out_path
          else f"\nDone. {n_final} words ready.")


if __name__ == "__main__":
    main()
