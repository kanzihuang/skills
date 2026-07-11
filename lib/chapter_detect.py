"""Shared chapter-boundary detection for English e-books.

Used by:
  - match_sentences.py: detect_story_start() → skip front-matter before
    sentence matching
  - extract_chapter.py: find_chapter_boundaries() → extract a specific
    chapter range

Does NOT assign per-word chapter metadata — this is purely text-structural
boundary detection (preamble → body).  Compatible with the "全文模式不获取、
不显示、不利用章节信息" design principle.
"""

from __future__ import annotations

import re

# ── compiled patterns ──────────────────────────────────────────────────────
_CHAPTER_RE = re.compile(
    r"(?:^|\n)"
    r"(?:"
    r"CHAPTER\s+(?:(?-i:[IVXLCDM]+)|\d+|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|"
    r"ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|"
    r"NINETEEN|TWENTY)\b|"
    r"CHAP\.\s+\d+\b|"
    r"(?:^|\n)(?:(?-i:[IVXLCDM]+))\.\s*\n|"
    r"(?:^|\n)PART\s+(?-i:[A-Z]+)\b|"
    r"(?:^|\n)Book\s+(?:(?-i:[IVXLCDM]+)|\d+)\b"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def detect_story_start(text: str) -> int:
    """Return char offset of first chapter heading (body start).

    Returns 0 if no chapter heading is found — the caller should process
    the full text as-is (conservative default for backward compatibility).
    """
    # ── primary: explicit chapter headings ──────────────────────────────
    m = _CHAPTER_RE.search(text)
    if m is not None:
        # The regex may include leading newlines in the match — find where
        # the heading text actually starts, then walk back to that line's start.
        match_text = m.group()
        leading_newlines = len(match_text) - len(match_text.lstrip("\n"))
        heading_start = m.start() + leading_newlines  # first non-\n char of match
        line_start = text.rfind("\n", 0, heading_start)
        return line_start + 1 if line_start >= 0 else 0

    # ── fallback: heuristic preamble detection ──────────────────────────
    # Some editions (e.g. Katherine Woods The Little Prince) have no
    # chapter headings.  Skip leading lines that match common front-matter
    # patterns until we hit narrative prose.
    lines = text.split("\n")
    _PRE_INDICATORS = re.compile(
        r"^\s*$|"                             # blank line
        r"^[A-Z][A-Z\s'-]{10,}$|"             # all-caps title (≥10 chars)
        r"^(?:by|By|Translated|Edited|Illustrated|Published|Copyright|ISBN|ISBN-13|LCCN)\b|"
        r"^\[.*\]$|"                           # [Illustration], [Frontispiece]
        r"^\*+\s*$"                            # *** (Project Gutenberg header/footer)
    )
    _BIO_INDICATORS = re.compile(
        r"\bwho was (?:a|an|the)\b|"           # "…who was a French author…"
        r"\bwrote\b.*\b(?:in|around)\s+\d{4}\b"  # "…wrote The Little Prince in 1943"
    )
    _META_INDICATORS = re.compile(
        r"\b(?:appears to be|is actually|some would say|"
        r"profound and deeply moving|"
        r"written in riddles|"
        r"laced with (?:philosophy|poetic))\b"
    )
    _NARRATIVE_OK = re.compile(r'^[A-Z"“].{40,}')  # capitalised or opening quote, ≥40 chars

    # Scan for the first line that looks like narrative prose.
    # Accumulate skipped chars for lines that are clearly front-matter.
    skipped = 0
    in_bio_paragraph = False   # True while inside a bio paragraph (skip continuations)
    for i, line in enumerate(lines):
        if _PRE_INDICATORS.match(line):
            skipped += len(line) + 1  # +1 for \n
            in_bio_paragraph = False  # blank line or section break ends bio paragraph
        elif _BIO_INDICATORS.search(line) and len(line) < 200:
            skipped += len(line) + 1
            in_bio_paragraph = True   # subsequent lines in same paragraph are bio
        elif in_bio_paragraph and len(line.strip()) > 0:
            # Continuation of a bio paragraph — skip regardless of content
            skipped += len(line) + 1
        elif _META_INDICATORS.search(line) and len(line) < 200:
            # Literary analysis / critical introduction (e.g. "X appears to
            # be a simple children's tale…").  Treat as preamble.
            skipped += len(line) + 1
        elif len(line.strip()) < 40 and not _NARRATIVE_OK.match(line):
            # Short non-narrative line (author name, subtitle, etc.) —
            # tentatively skip as front-matter
            skipped += len(line) + 1
        elif _NARRATIVE_OK.match(line):
            # Found a narrative line — stop here
            if 0 < skipped < len(text) * 0.4:
                return skipped
            break
        else:
            # Long line that doesn't look like narrative (possibly preamble
            # prose like editor introductions).  Be conservative: only
            # return if we've already skipped something.
            if skipped > 0 and i < min(10, len(lines) - 1):
                skipped += len(line) + 1  # skip it too, keep looking
                continue
            break

    return 0


def find_chapter_boundaries(text: str) -> list[dict]:
    """Return all detected chapter boundaries.

    Each entry:
        {"label": "CHAPTER I", "start": <char-offset>, "end": <char-offset>}

    The *end* of each chapter is the *start* of the next (or EOF for the
    last chapter).  An empty list means no chapter headings were found.
    """
    boundaries: list[dict] = []
    for m in _CHAPTER_RE.finditer(text):
        match_text = m.group()
        leading_newlines = len(match_text) - len(match_text.lstrip("\n"))
        heading_start = m.start() + leading_newlines
        line_start = text.rfind("\n", 0, heading_start) + 1
        boundaries.append({"label": match_text.strip(), "start": line_start})

    # Set end-of-chapter boundaries
    for i, b in enumerate(boundaries):
        if i + 1 < len(boundaries):
            b["end"] = boundaries[i + 1]["start"]
        else:
            b["end"] = len(text)

    return boundaries
