"""Test extract_chapter.py — boundaries-file option for books without headings."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

# Path to the extract_chapter script
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "lib", "scripts", "extract_chapter.py",
)


def _run(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run extract_chapter.py with given args."""
    venv_python = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "vocab-book", ".venv", "bin", "python3",
    )
    return subprocess.run(
        [venv_python, _SCRIPT] + args,
        capture_output=True, text=True,
    )


def _write_temp_json(data) -> str:
    """Write data as JSON to a temp file, return path."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="test-boundaries-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


def _write_temp_text(content: str) -> str:
    """Write text to a temp file, return path."""
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="test-book-")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


class TestBoundariesFile:
    """Tests for the --boundaries-file option."""

    def test_list_shows_external_boundaries(self):
        """--list with --boundaries-file prints chapter labels."""
        text_path = _write_temp_text("Chapter one text.\nChapter two text.\n")
        b_path = _write_temp_json([
            {"chapter": 1, "start": 0, "end": 18},
            {"chapter": 2, "start": 18, "end": 36},
        ])
        result = _run([text_path, "--boundaries-file", b_path, "--list"])
        assert "Using external boundaries" in result.stdout
        assert "Chapter 1" in result.stdout
        assert "Chapter 2" in result.stdout

    def test_extract_chapter_by_number(self):
        """Extract a specific chapter range from boundaries file."""
        text_path = _write_temp_text("AAAABBBBCCCCDDDD")
        b_path = _write_temp_json([
            {"start": 0, "end": 4},
            {"start": 4, "end": 8},
            {"start": 8, "end": 12},
            {"start": 12, "end": 16},
        ])
        result = _run([text_path, "--boundaries-file", b_path, "--chapter", "2"])
        assert result.stdout == "BBBB"

        result3 = _run([text_path, "--boundaries-file", b_path, "--chapter", "4"])
        assert result3.stdout == "DDDD"

    def test_extract_chapter_out_of_range(self):
        """Requesting a non-existent chapter exits with error."""
        text_path = _write_temp_text("AAAABBBB")
        b_path = _write_temp_json([
            {"start": 0, "end": 4},
            {"start": 4, "end": 8},
        ])
        result = _run([text_path, "--boundaries-file", b_path, "--chapter", "5"])
        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_invalid_json_errors(self):
        """Malformed JSON file produces a clear error."""
        fd, b_path = tempfile.mkstemp(suffix=".json", prefix="test-bad-")
        with os.fdopen(fd, "w") as f:
            f.write("not valid json {{{")
        text_path = _write_temp_text("anything")
        result = _run([text_path, "--boundaries-file", b_path, "--list"])
        assert result.returncode != 0
        assert "Error reading" in result.stderr

    def test_missing_keys_errors(self):
        """Boundary entry missing 'start' or 'end' produces error."""
        text_path = _write_temp_text("anything")
        b_path = _write_temp_json([{"chapter": 1, "start": 0}])  # no 'end'
        result = _run([text_path, "--boundaries-file", b_path, "--list"])
        assert result.returncode != 0
        assert "missing" in result.stderr

    def test_empty_array_errors(self):
        """Empty boundaries array produces error."""
        text_path = _write_temp_text("anything")
        b_path = _write_temp_json([])
        result = _run([text_path, "--boundaries-file", b_path, "--list"])
        assert result.returncode != 0
        assert "non-empty" in result.stderr

    def test_file_not_found_errors(self):
        """Non-existent boundaries file produces error."""
        text_path = _write_temp_text("anything")
        result = _run([text_path, "--boundaries-file", "/tmp/nonexistent_xyz.json", "--list"])
        assert result.returncode != 0

    def test_missing_label_defaults_to_chapter_n(self):
        """Boundary without 'label' gets default 'Chapter N'."""
        text_path = _write_temp_text("AAAABBBB")
        b_path = _write_temp_json([
            {"start": 0, "end": 4},
        ])
        result = _run([text_path, "--boundaries-file", b_path, "--list"])
        assert "Chapter 1" in result.stdout

    def test_preamble_with_boundaries_file(self):
        """--preamble extracts text before first chapter boundary."""
        preamble = "PREAMBLE TEXT HERE. "
        chapter = "Chapter one starts."
        text_path = _write_temp_text(preamble + chapter)
        b_path = _write_temp_json([{"start": len(preamble), "end": len(preamble + chapter)}])
        result = _run([text_path, "--boundaries-file", b_path, "--preamble"])
        assert result.stdout == preamble

    def test_extract_by_explicit_chapter_field(self):
        """--chapter N matches the 'chapter' field, not array index."""
        text_path = _write_temp_text("AAAABBBBCCCCDDDD")
        # Single entry with explicit chapter: 4 → --chapter 4 should work
        b_path = _write_temp_json([
            {"chapter": 4, "start": 0, "end": 4},
        ])
        result = _run([text_path, "--boundaries-file", b_path, "--chapter", "4"])
        assert result.returncode == 0
        assert result.stdout == "AAAA"

    def test_extract_by_mixed_chapter_fields(self):
        """Non-sequential chapter fields each extract correctly."""
        text_path = _write_temp_text("CH1_CH2_CH3_CH4_")
        b_path = _write_temp_json([
            {"chapter": 1, "start": 0, "end": 4},
            {"chapter": 4, "start": 4, "end": 8},
            {"chapter": 7, "start": 8, "end": 12},
        ])
        r1 = _run([text_path, "--boundaries-file", b_path, "--chapter", "1"])
        assert r1.stdout == "CH1_"
        r4 = _run([text_path, "--boundaries-file", b_path, "--chapter", "4"])
        assert r4.stdout == "CH2_"
        r7 = _run([text_path, "--boundaries-file", b_path, "--chapter", "7"])
        assert r7.stdout == "CH3_"

    def test_extract_chapter_out_of_range_boundaries(self):
        """--chapter with non-existent chapter field number shows available."""
        text_path = _write_temp_text("AAAABBBB")
        b_path = _write_temp_json([
            {"chapter": 4, "start": 0, "end": 4},
        ])
        result = _run([text_path, "--boundaries-file", b_path, "--chapter", "99"])
        assert result.returncode != 0
        assert "not found" in result.stderr
        assert "ch 4" in result.stderr  # available chapters listed

    def test_list_shows_chapter_fields(self):
        """--list with boundaries-file shows 'ch4:' not array index '1:'."""
        text_path = _write_temp_text("OneTwoThree")
        b_path = _write_temp_json([
            {"chapter": 4, "start": 0, "end": 3},
            {"chapter": 9, "start": 3, "end": 6},
        ])
        result = _run([text_path, "--boundaries-file", b_path, "--list"])
        assert "ch  4" in result.stdout or "ch 4" in result.stdout
        assert "ch  9" in result.stdout or "ch 9" in result.stdout
