"""Test filter_fulltext.py — full-text vocabulary filtering for vocab-book.

Covers:
  - Basic tokenization and lemmatization
  - COCA level range filtering
  - UUID suffix generation
  - JSON output structure

All tests share a single spaCy instance loaded at session start
via _run_filter_json(), cutting suite time from ~120s to ~1s.
"""

import json

import pytest


def _run_filter_json(
    text: str, *extra_args: str, nlp=None
) -> dict:
    """Run filter pipeline in-process and return parsed JSON.

    Accepts an optional pre-loaded spaCy nlp to avoid per-test
    load overhead (session fixture).  Falls back to loading on
    first call when not provided.
    """
    from filter_fulltext import run_filter

    # Parse extra_args into kwargs
    kwargs: dict = {}
    i = 0
    while i < len(extra_args):
        if extra_args[i] == "--basic-range" and i + 1 < len(extra_args):
            kwargs["basic_range"] = extra_args[i + 1]
            i += 2
        elif extra_args[i] == "--book-title" and i + 1 < len(extra_args):
            kwargs["book_title"] = extra_args[i + 1]
            i += 2
        elif extra_args[i] == "--book-author" and i + 1 < len(extra_args):
            kwargs["book_author"] = extra_args[i + 1]
            i += 2
        elif extra_args[i] == "--suffix" and i + 1 < len(extra_args):
            kwargs["suffix"] = extra_args[i + 1]
            i += 2
        else:
            i += 1

    return run_filter(text, nlp=nlp, **kwargs)


# Session-scoped spaCy fixture — loaded once, shared by all tests.
@pytest.fixture(scope="session")
def nlp():
    """Load spaCy once for the entire test session."""
    import spacy
    return spacy.load("en_core_web_sm")


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

    def test_summary_fields(self, nlp):
        """JSON output includes required summary fields."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        s = data["summary"]
        assert s["total_words"] > 0
        assert s["unique_surfaces"] > 0
        assert "coca_excluded" in s
        assert s["final"] > 0

    def test_suffix_is_12_hex_chars(self, nlp):
        """UUID suffix is 12 lowercase hex characters."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        suffix = data["suffix"]
        assert len(suffix) == 12
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_suffix_unique_per_run(self, nlp):
        """Each run generates a different suffix."""
        s1 = _run_filter_json(SAMPLE_TEXT, nlp=nlp)["suffix"]
        s2 = _run_filter_json(SAMPLE_TEXT, nlp=nlp)["suffix"]
        assert s1 != s2

    def test_in_coca_structure(self, nlp):
        """Each in_coca entry has lemma, rep, forms, coca_level."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        for entry in data["in_coca"]:
            assert "lemma" in entry
            assert "rep" in entry
            assert "forms" in entry
            assert "coca_level" in entry
            assert isinstance(entry["forms"], list)

    def test_no_chapters_field(self, nlp):
        """Output no longer includes chapters field (removed)."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        for entry in data["in_coca"]:
            assert "chapters" not in entry, \
                f"chapters field should not exist, got: {entry.get('chapters')}"

    def test_no_anki_fields(self, nlp):
        """Summary no longer includes Anki-related fields."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        s = data["summary"]
        assert "in_anki" not in s

    def test_excluded_structure(self, nlp):
        """Each excluded entry has lemma, rep, reason."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        for entry in data["excluded"]:
            assert "lemma" in entry
            assert "rep" in entry
            assert "reason" in entry

    def test_common_words_pass(self, nlp):
        """Common English words should pass COCA membership."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        lemmas = {e["lemma"] for e in data["in_coca"]}
        # These should all be in BNC/COCA 25000
        for word in ["dark", "night", "wind", "rain", "sea", "think", "edge"]:
            assert word in lemmas, f"Expected '{word}' to pass COCA check"

    def test_vbg_amod_adjective_kept_as_is(self, nlp):
        """Surface forms preserved as-is — filter no longer lemmatizes.

        Lemmatization (including VBG-amod guard) is now in match_sentences.py.
        Filter just passes through surface forms that pass COCA membership.
        """
        text = (
            "The bewildering complexity of the problem stunned everyone. "
            "He bewildered the audience with his rapid-fire questions."
        )
        data = _run_filter_json(text, nlp=nlp)
        lemmas = {e["lemma"] for e in data["in_coca"]}

        assert "bewildering" in lemmas, (
            f"Surface form 'bewildering' should pass as-is, got: {sorted(lemmas)}"
        )
        assert "bewildered" in lemmas, (
            f"Surface form 'bewildered' should pass as-is, got: {sorted(lemmas)}"
        )

    def test_vbg_verbal_still_reduces(self, nlp):
        """Surface forms preserved as-is — filter no longer lemmatizes.

        Lemmatization is now in match_sentences.py. 'boasting' passes COCA
        membership as a surface form.
        """
        text = "He was boasting about his achievements all day."
        data = _run_filter_json(text, nlp=nlp)
        lemmas = {e["lemma"] for e in data["in_coca"]}
        assert "boasting" in lemmas, (
            f"Surface form 'boasting' should pass as-is, got: {sorted(lemmas)}"
        )


class TestCOCARangeFiltering:
    """Tests for --basic-range filtering."""

    def test_range_1_1_excludes_most(self, nlp):
        """Level 1-1 should only include the most frequent words."""
        data_all = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        data_range = _run_filter_json(SAMPLE_TEXT, "--basic-range", "1-1", nlp=nlp)
        assert data_range["summary"]["final"] <= data_all["summary"]["final"]

    def test_stdout_has_expected_sections(self, nlp, capsys):
        """Stdout output has SUMMARY, IN_COCA, EXCLUDED sections."""
        _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        captured = capsys.readouterr()
        assert "SUMMARY:" in captured.out
        assert "---IN_COCA---" in captured.out
        assert "---EXCLUDED---" in captured.out


class TestBandsAndSuffix:
    """Tests for --basic-range band parsing and --suffix reuse."""

    def test_default_bands_when_no_range(self, nlp):
        """JSON includes default bands when no --basic-range specified."""
        data = _run_filter_json(SAMPLE_TEXT, nlp=nlp)
        assert "bands" in data
        assert data["is_bilateral"] is False
        bands = data["bands"]
        assert len(bands) == 4
        assert bands[0] == {"name": "COCA 1-3", "lo": 1, "hi": 3}
        assert bands[-1] == {"name": "COCA 10", "lo": 10, "hi": 25}

    def test_single_bilateral_range(self, nlp):
        """--basic-range 3-10 → one COCA 3-10 band, is_bilateral=True."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "3-10", nlp=nlp)
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 1
        assert bands[0] == {"name": "COCA 3-10", "lo": 3, "hi": 10}

    def test_multi_bilateral_ranges(self, nlp):
        """--basic-range 3-5,6-8,9-10 → three bands."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "3-5,6-8,9-10", nlp=nlp)
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 3
        assert bands[0] == {"name": "COCA 3-5", "lo": 3, "hi": 5}
        assert bands[1] == {"name": "COCA 6-8", "lo": 6, "hi": 8}
        assert bands[2] == {"name": "COCA 9-10", "lo": 9, "hi": 10}

    def test_single_sided_lower_bound(self, nlp):
        """--basic-range 3 (仅下限) → default bands, is_bilateral=False."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "3", nlp=nlp)
        assert data["is_bilateral"] is False
        bands = data["bands"]
        assert len(bands) == 4  # default

    def test_single_sided_upper_bound(self, nlp):
        """--basic-range -10 (仅上限) → default bands, is_bilateral=False."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "-10", nlp=nlp)
        assert data["is_bilateral"] is False
        bands = data["bands"]
        assert len(bands) == 4  # default

    def test_multi_bare_numbers_as_separate_bands(self, nlp):
        """--basic-range 8,9 → two single-level bands, is_bilateral=True."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "8,9", nlp=nlp)
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 2
        assert bands[0] == {"name": "COCA 8", "lo": 8, "hi": 8}
        assert bands[1] == {"name": "COCA 9", "lo": 9, "hi": 9}

    def test_multi_bare_numbers_three_levels(self, nlp):
        """--basic-range 5,7,10 → three single-level bands."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "5,7,10", nlp=nlp)
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 3
        assert bands[0] == {"name": "COCA 5", "lo": 5, "hi": 5}
        assert bands[2] == {"name": "COCA 10", "lo": 10, "hi": 10}

    def test_single_bare_number_unchanged(self, nlp):
        """--basic-range 3 (single bare number) → legacy single-sided behavior."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "3", nlp=nlp)
        assert data["is_bilateral"] is False
        bands = data["bands"]
        assert len(bands) == 4  # default bands

    def test_overlap_error(self, nlp):
        """Overlapping bands → FilterError."""
        from filter_fulltext import FilterError
        with pytest.raises(FilterError, match="overlaps"):
            _run_filter_json(SAMPLE_TEXT, "--basic-range", "4-6,6-8", nlp=nlp)

    def test_lo_greater_than_hi_error(self, nlp):
        """lo > hi → FilterError."""
        from filter_fulltext import FilterError
        with pytest.raises(FilterError, match="lo\\(6\\) > hi\\(4\\)"):
            _run_filter_json(SAMPLE_TEXT, "--basic-range", "6-4", nlp=nlp)

    def test_out_of_range_error(self, nlp):
        """Band out of 1-25 range → FilterError."""
        from filter_fulltext import FilterError
        with pytest.raises(FilterError, match="out of COCA range"):
            _run_filter_json(SAMPLE_TEXT, "--basic-range", "3-30", nlp=nlp)

    def test_single_level_band(self, nlp):
        """--basic-range 1-1 → single-level band is valid."""
        data = _run_filter_json(SAMPLE_TEXT, "--basic-range", "1-1", nlp=nlp)
        assert data["is_bilateral"] is True
        bands = data["bands"]
        assert len(bands) == 1
        assert bands[0] == {"name": "COCA 1", "lo": 1, "hi": 1}

    def test_suffix_reuse(self, nlp):
        """--suffix provides deterministic UUID."""
        data1 = _run_filter_json(SAMPLE_TEXT, "--suffix", "ab12cd34ef56", nlp=nlp)
        assert data1["suffix"] == "ab12cd34ef56"

    def test_suffix_invalid_length(self, nlp):
        """Invalid --suffix (wrong length) → FilterError."""
        from filter_fulltext import FilterError
        with pytest.raises(FilterError, match="12 hex chars"):
            _run_filter_json(SAMPLE_TEXT, "--suffix", "too_short", nlp=nlp)

    def test_suffix_invalid_chars(self, nlp):
        """Invalid --suffix (non-hex chars) → FilterError."""
        from filter_fulltext import FilterError
        with pytest.raises(FilterError, match="12 hex chars"):
            _run_filter_json(SAMPLE_TEXT, "--suffix", "gggggggggggg", nlp=nlp)

    def test_comma_single_sided_in_multi(self, nlp):
        """Single-sided bands in comma context → FilterError."""
        from filter_fulltext import FilterError
        with pytest.raises(FilterError, match="missing boundary"):
            _run_filter_json(SAMPLE_TEXT, "--basic-range", "4-,6-8", nlp=nlp)

    # ── hyphen-only word exclusion ──────────────────────────────────────

    def test_hyphen_only_word_excluded(self, nlp):
        """Words only appearing in hyphenated compounds are excluded."""
        text = "He wore a half-garland on his head."
        data = _run_filter_json(text, nlp=nlp)
        in_coca_words = {e["lemma"] for e in data["in_coca"]}
        assert "garland" not in in_coca_words, \
            f"'garland' only appears in 'half-garland', should be excluded"

    def test_standalone_word_kept_when_also_hyphenated(self, nlp):
        """Word appearing both standalone and in compound is kept."""
        text = "He put the mast down. The mast-head was broken."
        data = _run_filter_json(text, nlp=nlp)
        in_coca_words = {e["lemma"] for e in data["in_coca"]}
        assert "mast" in in_coca_words, \
            f"'mast' appears standalone, should be kept"

    def test_hyphen_only_stricken_excluded(self, nlp):
        """'stricken' only in 'panic-stricken' → excluded."""
        text = "She made a panic-stricken dash for the door."
        data = _run_filter_json(text, nlp=nlp)
        in_coca_words = {e["lemma"] for e in data["in_coca"]}
        assert "stricken" not in in_coca_words, \
            f"'stricken' only in 'panic-stricken', should be excluded"

    # ── PROPN-only exclusion ────────────────────────────────────────────

    def test_propn_only_jota_excluded(self, nlp):
        """Proper noun 'Jota' (Spanish letter, mid-sentence capital) excluded."""
        text = 'He said Jota for the letter J.'
        data = _run_filter_json(text, nlp=nlp)
        in_coca_words = {e["lemma"] for e in data["in_coca"]}
        assert "jota" not in in_coca_words, \
            f"'Jota' is PROPN-only, should be excluded (not reduced to 'jot')"

    def test_propn_but_also_common_noun_kept(self, nlp):
        """Word that appears as both PROPN and common noun is kept."""
        text = "Boa constrictors are snakes. The boa swallowed a rat."
        data = _run_filter_json(text, nlp=nlp)
        in_coca_words = {e["lemma"] for e in data["in_coca"]}
        # "boa" appears as PROPN and also lowercase → not PROPN-only
        assert "boa" in in_coca_words, \
            f"'boa' appears in both cases, should be kept"
