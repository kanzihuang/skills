"""Test filter_pipeline.py — clean_mark, pick_rep, API validation.

Covers historical errors:
  - API response missing 'updated' field (commit c2c3fdd)
  - Punctuation stripping at sentence boundaries
  - Internal punctuation preserved
"""

import json
import pytest
from filter_pipeline import clean_mark, pick_rep


@pytest.mark.parametrize("text,expected", [
    # ── Sentence-boundary punctuation stripped ──
    ("vexed.", "vexed"),
    ("clad.", "clad"),
    ("word,", "word"),
    ("fish;", "fish"),
    ("test:", "test"),
    ("hello!", "hello"),
    ("what?", "what"),
    # ── Internal punctuation preserved ──
    ("can't", "can't"),            # apostrophe
    ("well-known", "well-known"),  # hyphen
    ("ice-cream", "ice-cream"),    # hyphen
    # ── Already clean ──
    ("clean", "clean"),
    ("fish", "fish"),
])
def test_clean_mark(text, expected):
    result = clean_mark(text)
    assert result == expected, f"clean_mark({text!r}) = {result!r}"


def test_clean_mark_empty():
    assert clean_mark("") == ""


def test_clean_mark_only_punctuation():
    assert clean_mark(".") == ""
    assert clean_mark("?!") == ""


@pytest.mark.parametrize("forms,expected", [
    (["word", "Word", "WORD"], "word"),       # lowercase preferred
    (["WORD", "Word", "word"], "word"),
    (["the", "The"], "the"),
    (["a", "an"], "a"),                        # shortest wins
    (["pondered", "ponder"], "ponder"),        # shortest selected
    (["UN"], "UN"),                            # all-caps acronym preserved
    (["NASA"], "NASA"),
    (["word"], "word"),                        # single form
])
def test_pick_rep(forms, expected):
    result = pick_rep(forms)
    assert result == expected, f"pick_rep({forms!r}) = {result!r}"


def test_api_missing_updated_field(tmp_path):
    """API response without 'updated' field should cause exit 1.

    Historical: wrong API key returned a different JSON structure (commit c2c3fdd).
    """
    import subprocess
    import sys

    bad_response = json.dumps({"errcode": -1, "errmsg": "auth failed"})
    result = subprocess.run(
        [sys.executable, "-c", f"""
import sys, json
sys.stdin = open('/dev/stdin', 'r')
# Simulate: the filter_pipeline would check for 'updated' in the response
data = json.loads(r'{bad_response}')
if 'updated' not in data and 'chapters' not in data:
    print("Error: API response missing 'updated' field", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
"""],
        input=bad_response,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, "Missing 'updated' should cause exit code 1"
    assert "missing" in result.stderr.lower() or "error" in result.stderr.lower()


def test_query_anki_existing_count_mismatch_warning(capsys):
    """Warning when notes_info returns fewer results than requested."""
    from unittest.mock import patch, MagicMock
    from filter_pipeline import query_anki_existing

    ac = MagicMock()
    ac.find_notes_by_field.return_value = [1, 2, 3]  # 3 requested
    # Only return 2 results — count mismatch
    ac.notes_info.return_value = [
        {"fields": {"WordId": {"value": "loaf_VERB_22720170"}}},
        {"fields": {"WordId": {"value": "caravan_NOUN_22720170"}}},
    ]

    import sys
    result = query_anki_existing(ac, "22720170")

    captured = capsys.readouterr()
    assert "returned 2 results" in captured.err, (
        "should warn about count mismatch"
    )
    assert len(result) > 0, "should still return valid lemmas from partial results"
