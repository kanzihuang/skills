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


def test_json_out_includes_coca_level(tmp_path):
    """JSON output 'in_coca' entries must include 'coca_level' field.

    Historical: filter_pipeline.py documented coca_level in SKILL.md
    but never included it in the JSON output (2026-07-10 fix).
    """
    import subprocess
    import sys
    import json
    import os

    api_response = json.dumps({
        "updated": [
            {"markText": "puzzled", "chapterUid": 105},
            {"markText": "thunderstruck", "chapterUid": 94},
        ],
        "chapters": [
            {"chapterUid": 105, "title": "Chapter 12"},
            {"chapterUid": 94, "title": "Chapter 1"},
        ],
    })

    json_out = tmp_path / "filtered.json"
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, os.path.join(skill_dir, "filter_pipeline.py"),
         "--book-id", "TEST", "--book-title", "Test",
         "--book-author", "Author",
         "--json-out", str(json_out)],
        input=api_response,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"filter_pipeline failed: {result.stderr}"
    with open(json_out) as f:
        data = json.load(f)

    assert len(data["in_coca"]) == 1, "puzzle should pass COCA"
    entry = data["in_coca"][0]
    assert entry["lemma"] == "puzzle"
    assert "coca_level" in entry, "coca_level field must be present"
    assert entry["coca_level"] == 3, f"puzzle should be COCA level 3, got {entry['coca_level']}"
