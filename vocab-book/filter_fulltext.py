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


# ── band parsing ─────────────────────────────────────────────────────────────

DEFAULT_BANDS: list[tuple[int, int]] = [(1, 3), (4, 6), (7, 9), (10, 25)]


def _is_bilateral(band_str: str) -> bool:
    """Check if a band string is bilateral (has both lo and hi)."""
    return "-" in band_str and not band_str.startswith("-") and not band_str.endswith("-")


def parse_bands(
    arg: str | None,
) -> tuple[list[tuple[int, int]], int, int, bool]:
    """Parse --basic-range into (bands, filter_lo, filter_hi, is_bilateral).

    is_bilateral = all bands have explicit lo and hi → use specified bands.
    Otherwise → use DEFAULT_BANDS for deck structure.

    Returns (bands, filter_lo, filter_hi, is_bilateral).
    """
    bilateral_bands: list[tuple[int, int]] = []
    use_default = True
    filter_lo = 1
    filter_hi = 25

    if not arg:
        return DEFAULT_BANDS, filter_lo, filter_hi, False

    parts = [p.strip() for p in arg.split(",") if p.strip()]

    # Classify parts before processing
    bare_numbers: list[int] = []
    has_bilateral = False
    for p in parts:
        if _is_bilateral(p):
            has_bilateral = True
        elif "-" not in p:
            try:
                bare_numbers.append(int(p))
            except ValueError:
                pass  # handled below

    # Multiple bare numbers with no bilateral bands → each is a
    # single-level band (e.g. "8,9" → COCA 8 and COCA 9 separately)
    if len(bare_numbers) > 1 and not has_bilateral:
        for n in bare_numbers:
            if n < 1 or n > 25:
                print(f"Error: level '{n}' out of COCA range (1-25)",
                      file=sys.stderr)
                sys.exit(1)
            bilateral_bands.append((n, n))
        filter_lo = min(bare_numbers)
        filter_hi = max(bare_numbers)
        # Skip the per-part loop below — we've handled everything
        parts = []

    for i, p in enumerate(parts, 1):
        if _is_bilateral(p):
            lo_str, hi_str = p.split("-", 1)
            try:
                lo, hi = int(lo_str), int(hi_str)
            except ValueError:
                print(f"Error: band '{p}' contains non-integer values",
                      file=sys.stderr)
                sys.exit(1)
            bilateral_bands.append((lo, hi))
        elif "-" in p:
            # Single-sided: "3-" or "-10"
            if len(parts) > 1:
                print(f"Error: band {i} ('{p}') missing boundary — "
                      f"bilateral bands required when using commas",
                      file=sys.stderr)
                sys.exit(1)
            # Single-sided as sole argument → filter-only, default bands
            try:
                if p.startswith("-"):
                    filter_hi = int(p[1:])
                else:
                    filter_lo = int(p[:-1])
            except ValueError:
                print(f"Error: invalid band value '{p}'", file=sys.stderr)
                sys.exit(1)
        else:
            # Bare number (e.g. "3") → single-sided, use default bands
            try:
                filter_lo = int(p)
                filter_hi = 25
            except ValueError:
                print(f"Error: invalid band value '{p}'", file=sys.stderr)
                sys.exit(1)

    if bilateral_bands:
        # Validate
        for i, (lo, hi) in enumerate(bilateral_bands, 1):
            if lo > hi:
                print(f"Error: band '{lo}-{hi}' lo({lo}) > hi({hi})",
                      file=sys.stderr)
                sys.exit(1)
            if lo < 1 or hi > 25:
                print(f"Error: band '{lo}-{hi}' out of COCA range (1-25)",
                      file=sys.stderr)
                sys.exit(1)

        # Check for overlap between sorted bands
        sorted_bands = sorted(bilateral_bands)
        for i in range(len(sorted_bands) - 1):
            if sorted_bands[i][1] >= sorted_bands[i + 1][0]:
                print(f"Error: band '{sorted_bands[i][0]}-{sorted_bands[i][1]}' "
                      f"overlaps with '{sorted_bands[i + 1][0]}-{sorted_bands[i + 1][1]}'",
                      file=sys.stderr)
                sys.exit(1)

        filter_lo = min(b[0] for b in bilateral_bands)
        filter_hi = max(b[1] for b in bilateral_bands)
        return sorted_bands, filter_lo, filter_hi, True

    # Single-sided: use default bands
    return DEFAULT_BANDS, filter_lo, filter_hi, False


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
    basic_range_arg: Optional[str] = None
    json_out_path: Optional[str] = None
    book_title: Optional[str] = None
    book_author: Optional[str] = None
    suffix: Optional[str] = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--basic-range" and i + 1 < len(args):
            basic_range_arg = args[i + 1]
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
        elif args[i] == "--suffix" and i + 1 < len(args):
            suffix = args[i + 1]
            i += 2
        else:
            i += 1

    # Parse bands + filter range
    bands, basic_min, basic_max, is_bilateral = parse_bands(basic_range_arg)

    # -- pre-flight: verify spaCy is functional --------------------------------
    if not _check_spacy():
        sys.exit(1)

    # -- read stdin -----------------------------------------------------------
    text = sys.stdin.read()
    if not text.strip():
        print("Error: no text provided on stdin", file=sys.stderr)
        sys.exit(1)

    # Validate plain-text format (defence-in-depth against HTML wrappers)
    from lib.utils import validate_plain_text
    validate_plain_text(text, "stdin")

    coca_set = load_coca()

    # Generate or reuse UUID suffix for WordId/audio namespace isolation
    if suffix:
        # Validate: must be exactly 12 lowercase hex chars
        if not (len(suffix) == 12
                and all(c in "0123456789abcdef" for c in suffix)):
            print(f"Error: --suffix must be 12 hex chars, got '{suffix}'",
                  file=sys.stderr)
            sys.exit(1)
    else:
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
        # Build band entries; last default band (10,25) → "COCA 10"
        band_entries: list[dict] = []
        for idx, (lo, hi) in enumerate(bands):
            if not is_bilateral and idx == len(bands) - 1 and lo == 10 and hi == 25:
                name = "COCA 10"
            elif lo == hi:
                name = f"COCA {lo}"
            else:
                name = f"COCA {lo}-{hi}"
            band_entries.append({"name": name, "lo": lo, "hi": hi})

        json_out = {
            "book_title": book_title or "",
            "book_author": book_author or "",
            "suffix": suffix,
            "bands": band_entries,
            "is_bilateral": is_bilateral,
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
