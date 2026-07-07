#!/usr/bin/env python3
"""Extract a specific chapter from a book's full text.

Detects chapter headings (CHAPTER I, Chapter 1, CHAP. 1, Roman numerals,
PART ONE, Book I) and extracts the text range for the requested chapter.

Usage:
    python extract_chapter.py book.txt --chapter 1
    python extract_chapter.py book.txt --chapter 1 --output ch01.txt
    python extract_chapter.py book.txt --list
    python extract_chapter.py book.txt --preamble
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.chapter_detect import find_chapter_boundaries


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a specific chapter from a book's full text."
    )
    parser.add_argument("source_text", help="Path to the book text file")
    parser.add_argument("--chapter", "-c", type=int, default=None,
                        help="Chapter number to extract (1-indexed)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output file path (default: stdout)")
    parser.add_argument("--list", action="store_true",
                        help="List all detected chapters and exit")
    parser.add_argument("--preamble", action="store_true",
                        help="Extract only the preamble (text before first chapter)")
    args = parser.parse_args()

    with open(args.source_text, encoding="utf-8") as f:
        text = f.read()

    boundaries = find_chapter_boundaries(text)

    if args.list:
        if not boundaries:
            print("No chapter headings detected.")
        else:
            for i, b in enumerate(boundaries, 1):
                length = b["end"] - b["start"]
                preview = text[b["start"]:b["start"] + 80].replace("\n", " | ")
                print(f"  {i:2d}. {b['label']:<20s} ({length:>6d} chars)  {preview}…")
        return

    if args.preamble:
        if not boundaries:
            result = ""  # no chapters → no preamble (full text is story)
        else:
            result = text[:boundaries[0]["start"]]
    elif args.chapter is not None:
        idx = args.chapter - 1
        if idx < 0 or idx >= len(boundaries):
            available = ", ".join(
                f"{i}: '{b['label']}'" for i, b in enumerate(boundaries, 1)
            )
            print(
                f"Error: chapter {args.chapter} not found. "
                f"Detected chapters: {available or 'none'}",
                file=sys.stderr,
            )
            sys.exit(1)
        result = text[boundaries[idx]["start"]:boundaries[idx]["end"]]
    else:
        # Default: list chapters
        if not boundaries:
            print("No chapter headings detected.")
        else:
            for i, b in enumerate(boundaries, 1):
                length = b["end"] - b["start"]
                preview = text[b["start"]:b["start"] + 80].replace("\n", " | ")
                print(f"  {i:2d}. {b['label']:<20s} ({length:>6d} chars)  {preview}…")
        return

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Extracted {len(result)} chars → {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    _main()
