"""Test filter_fulltext.py — full-text vocabulary filtering for vocab-book.

Covers:
  - Basic tokenization and lemmatization
  - COCA level range filtering
  - UUID suffix generation
  - JSON output structure
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

# Path to filter_fulltext.py
_FILTER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "filter_fulltext.py",
)


def _run_filter(text: str, *extra_args: str) -> "subprocess.CompletedProcess[str]":
    """Run filter_fulltext.py with *text* on stdin and return completed process."""
    return subprocess.run(
        [sys.executable, _FILTER_SCRIPT, *extra_args],
        input=text,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_filter_json(text: str, *extra_args: str) -> dict:
    """Run filter_fulltext.py with --json-out and return parsed JSON."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = _run_filter(text, "--json-out", tmp_path, *extra_args)
        with open(tmp_path, encoding="utf-8") as f:
            return json.load(f)
    finally:
        os.unlink(tmp_path)


SAMPLE_TEXT = (
    "It was a dark and stormy night. The wind howled through the trees, "
    "and the rain came down in torrents. A solitary figure stood at the "
    "edge of the cliff, gazing out at the churning sea below. He had come "
    "here to think, to ponder the choices that had led him to this moment. "
    "The blundering mistakes of his youth seemed so distant now, yet the "
    "consequences remained as vivid as ever."
)


class TestBasicFiltering:
    """Tests for basic filtering without COCA range."""

    def test_summary_fields(self):
        """JSON output includes required summary fields."""
        data = _run_filter_json(SAMPLE_TEXT)
        s = data["summary"]
        assert s["total_words"] > 0
        assert s["unique_surfaces"] > 0
        assert "coca_excluded" in s
        assert s["final"] > 0

    def test_suffix_is_12_hex_chars(self):
        """UUID suffix is 12 lowercase hex characters."""
        data = _run_filter_json(SAMPLE_TEXT)
        suffix = data["suffix"]
        assert len(suffix) == 12
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_suffix_unique_per_run(self):
        """Each run generates a different suffix."""
        s1 = _run_filter_json(SAMPLE_TEXT)["suffix"]
        s2 = _run_filter_json(SAMPLE_TEXT)["suffix"]
        assert s1 != s2

    def test_in_coca_structure(self):
        """Each in_coca entry has lemma, rep, forms, coca_level."""
        data = _run_filter_json(SAMPLE_TEXT)
        for entry in data["in_coca"]:
            assert "lemma" in entry
            assert "rep" in entry
            assert "forms" in entry
            assert "coca_level" in entry
            assert isinstance(entry["forms"], list)

    def test_no_chapters_field(self):
        """Output no longer includes chapters field (removed)."""
        data = _run_filter_json(SAMPLE_TEXT)
        for entry in data["in_coca"]:
            assert "chapters" not in entry, \
                f"chapters field should not exist, got: {entry.get('chapters')}"

    def test_no_anki_fields(self):
        """Summary no longer includes Anki-related fields."""
        data = _run_filter_json(SAMPLE_TEXT)
        s = data["summary"]
        assert "in_anki" not in s

    def test_excluded_structure(self):
        """Each excluded entry has lemma, rep, reason."""
        data = _run_filter_json(SAMPLE_TEXT)
        for entry in data["excluded"]:
            assert "lemma" in entry
            assert "rep" in entry
            assert "reason" in entry

    def test_common_words_pass(self):
        """Common English words should pass COCA membership."""
        data = _run_filter_json(SAMPLE_TEXT)
        lemmas = {e["lemma"] for e in data["in_coca"]}
        # These should all be in BNC/COCA 25000
        for word in ["dark", "night", "wind", "rain", "sea", "think", "edge"]:
            assert word in lemmas, f"Expected '{word}' to pass COCA check"

    def test_vbg_amod_adjective_kept_as_is(self):
        """Surface forms preserved as-is — filter no longer lemmatizes.

        Lemmatization (including VBG-amod guard) is now in match_sentences.py.
        Filter just passes through surface forms that pass COCA membership.
        """
        text = (
            "The bewildering complexity of the problem stunned everyone. "
            "He bewildered the audience with his rapid-fire questions."
        )
        data = _run_filter_json(text)
        lemmas = {e["lemma"] for e in data["in_coca"]}

        assert "bewildering" in lemmas, (
            f"Surface form 'bewildering' should pass as-is, got: {sorted(lemmas)}"
        )
        assert "bewildered" in lemmas, (
            f"Surface form 'bewildered' should pass as-is, got: {sorted(lemmas)}"
        )

    def test_vbg_verbal_still_reduces(self):
        """Surface forms preserved as-is — filter no longer lemmatizes.

        Lemmatization is now in match_sentences.py. 'boasting' passes COCA
        membership as a surface form.
        """
        text = "He was boasting about his achievements all day."
        data = _run_filter_json(text)
        lemmas = {e["lemma"] for e in data["in_coca"]}
        assert "boasting" in lemmas, (
            f"Surface form 'boasting' should pass as-is, got: {sorted(lemmas)}"
        )


class TestCOCARangeFiltering:
    """Tests for --basic-range filtering."""

    def test_range_1_1_excludes_most(self):
        """Level 1-1 should only include the most frequent words."""
        data_all = _run_filter_json(SAMPLE_TEXT)
        data_range = _run_filter_json(SAMPLE_TEXT, "--basic-range", "1-1")
        assert data_range["summary"]["final"] <= data_all["summary"]["final"]

    def test_stdout_has_expected_sections(self):
        """Stdout output has SUMMARY, IN_COCA, EXCLUDED sections."""
        result = _run_filter(SAMPLE_TEXT)
        assert "SUMMARY:" in result.stdout
        assert "---IN_COCA---" in result.stdout
        assert "---EXCLUDED---" in result.stdout


class TestBandsAndSuffix:
    """Tests for --basic-range band parsing and --suffix reuse."""

    def test_default_bands_when_no_range(self):
        """JSON includes default bands when no --basic-range specified."""
        data = _run_filter_json(SAMPLE_TEXT)
        assert "bands" in data
        assert data["is_bilateral"] is False
        bands = data["bands"]
        assert len(bands) == 4
        assert bands[0] == {"name": "COCA 1-3", "lo": 1, "hi": 3}
        assert bands[-1] == {"name": "COCA 10", "lo": 10, "hi": 25}

    def test_single_bilateral_range(self):
        """--basic-range 3-10 → one COCA 3-10 band, is_bilateral=True."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "3-10")
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 1
        assert bands[0] == {"name": "COCA 3-10", "lo": 3, "hi": 10}

    def test_multi_bilateral_ranges(self):
        """--basic-range 3-5,6-8,9-10 → three bands."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "3-5,6-8,9-10")
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 3
        assert bands[0] == {"name": "COCA 3-5", "lo": 3, "hi": 5}
        assert bands[1] == {"name": "COCA 6-8", "lo": 6, "hi": 8}
        assert bands[2] == {"name": "COCA 9-10", "lo": 9, "hi": 10}

    def test_single_sided_lower_bound(self):
        """--basic-range 3 (仅下限) → default bands, is_bilateral=False."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "3")
        assert data["is_bilateral"] is False
        bands = data["bands"]
        assert len(bands) == 4  # default

    def test_single_sided_upper_bound(self):
        """--basic-range -10 (仅上限) → default bands, is_bilateral=False."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "-10")
        assert data["is_bilateral"] is False
        bands = data["bands"]
        assert len(bands) == 4  # default

    def test_overlap_error(self):
        """Overlapping bands → exit with error."""
        result = _run_filter(SAMPLE_TEXT, "--basic-range", "4-6,6-8")
        assert result.returncode != 0
        assert "overlaps" in result.stderr

    def test_lo_greater_than_hi_error(self):
        """lo > hi → exit with error."""
        result = _run_filter(SAMPLE_TEXT, "--basic-range", "6-4")
        assert result.returncode != 0

    def test_out_of_range_error(self):
        """Band out of 1-25 range → exit with error."""
        result = _run_filter(SAMPLE_TEXT, "--basic-range", "3-30")
        assert result.returncode != 0

    def test_single_level_band(self):
        """--basic-range 1-1 → single-level band is valid."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "1-1")
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 1
        assert bands[0] == {"name": "COCA 1", "lo": 1, "hi": 1}

    def test_suffix_reuse(self):
        """--suffix provides deterministic UUID."""
        data1 = _run_filter_json(SAMPLE_TEXT, "--suffix", "ab12cd34ef56")
        assert data1["suffix"] == "ab12cd34ef56"

    def test_suffix_invalid_length(self):
        """Invalid --suffix (wrong length) → exit with error."""
        result = _run_filter(SAMPLE_TEXT, "--suffix", "too_short")
        assert result.returncode != 0

    def test_suffix_invalid_chars(self):
        """Invalid --suffix (non-hex chars) → exit with error."""
        result = _run_filter(SAMPLE_TEXT, "--suffix", "gggggggggggg")
        assert result.returncode != 0

    def test_comma_single_sided_in_multi(self):
        """Single-sided bands in comma context → error."""
        result = _run_filter(SAMPLE_TEXT, "--basic-range", "4-,6-8")
        assert result.returncode != 0
        assert "missing boundary" in result.stderr
