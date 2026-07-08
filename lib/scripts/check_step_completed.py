#!/usr/bin/env python3
"""Validate that mandatory Claude workflow steps were actually executed.

Checks the input JSON for mechanical signs that a step was skipped.
Does NOT validate semantic quality — that is the Claude agent's job.
This script is a floor guardrail: it ensures the step was at least RUN.

Usage:
    python check_step_completed.py /tmp/vocab-anki-input-<id>.json --step 2B
    python check_step_completed.py /tmp/vocab-anki-input-<id>.json --step 2F
    python check_step_completed.py /tmp/vocab-anki-input-<id>.json --step all

Exit codes:
    0 — step appears to have been completed
    1 — step was likely skipped (mandatory checks failed)
"""

from __future__ import annotations

import argparse
import json
import re
import sys

_QUOTES = '"' + '“' + '”' + "'" + '‘' + '’'


def _has_sentence_ending(sent: str) -> bool:
    """Check sentence ends with . ! ? after stripping trailing quotes."""
    stripped = sent.rstrip().rstrip(_QUOTES)
    return bool(stripped) and stripped[-1] in ('.', '!', '?')


def _check_2b(words: list[dict]) -> list[str]:
    """Check if Step 2B (sentence selection + truncation) was executed.

    Signs of SKIP:
      - Any sentence > 250 chars without truncation
      - Any sentence starting with lowercase (fragment)
    """
    warnings: list[str] = []
    for w in words:
        word = w.get("word", "?")
        sent = w.get("sentence", "")

        if not sent:
            warnings.append(f"[{word}] sentence is empty — Step 2B not run")
            continue

        # Check for overlong untruncated sentences
        clean = re.sub(r"<[^>]+>", "", sent)
        if len(clean) > 250:
            warnings.append(
                f"[{word}] sentence is {len(clean)} chars (>250) without "
                f"truncation — Step 2B likely skipped"
            )

        # Check sentence starts with capital or opening quote
        first_char = clean.lstrip()[0] if clean.lstrip() else ""
        if first_char and first_char not in '"“\'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            warnings.append(
                f"[{word}] sentence starts with '{first_char}' — may be a "
                f"fragment, Step 2B completeness check likely skipped"
            )

        # Check sentence has terminating punctuation
        if not _has_sentence_ending(clean):
            warnings.append(
                f"[{word}] sentence lacks terminating punctuation (. ! ?) — "
                f"may be a fragment, verify in Step 2B"
            )

    return warnings


def _check_2f(words: list[dict]) -> list[str]:
    """Check if Step 2F (content validation) was executed.

    Signs of SKIP:
      - Any word missing definition_cn
      - Any word missing ipa
      - definition_cn not matching expected [pos] format
    """
    warnings: list[str] = []
    for w in words:
        word = w.get("word", "?")

        dfn = w.get("definition_cn", "")
        if not dfn:
            warnings.append(f"[{word}] missing definition_cn")
        elif not re.match(r"^\[(n\.|v\.|adj\.|adv\.|prep\.|conj\.)\]\s+\S", dfn):
            warnings.append(
                f"[{word}] definition_cn format unexpected: '{dfn[:60]}'"
            )

        ipa_val = w.get("ipa", "")
        if not ipa_val:
            warnings.append(f"[{word}] missing ipa")
        elif not (ipa_val.startswith("/") and "/" in ipa_val[1:]):
            warnings.append(f"[{word}] ipa format unexpected: '{ipa_val}'")

    return warnings


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Check that mandatory Claude workflow steps were completed."
    )
    parser.add_argument("input_json", help="Path to vocab-anki input JSON")
    parser.add_argument(
        "--step", choices=["2B", "2F", "all"], default="all",
        help="Which step to check (default: all)",
    )
    args = parser.parse_args()

    with open(args.input_json, encoding="utf-8") as f:
        data = json.load(f)

    words = data.get("words", [])
    all_warnings: list[str] = []

    if args.step in ("2B", "all"):
        w2b = _check_2b(words)
        if w2b:
            all_warnings.append(
                f"Step 2B may have been SKIPPED ({len(w2b)} issue(s)):"
            )
            all_warnings.extend(f"  {w}" for w in w2b)

    if args.step in ("2F", "all"):
        w2f = _check_2f(words)
        if w2f:
            all_warnings.append(
                f"Step 2F may have been SKIPPED ({len(w2f)} issue(s)):"
            )
            all_warnings.extend(f"  {w}" for w in w2f)

    if all_warnings:
        for line in all_warnings:
            print(line, file=sys.stderr)
        print(
            "\n⚠️  Mandatory step(s) were likely skipped. "
            "Re-run the missing step(s) before syncing.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print("Step completion check PASSED", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    _main()
