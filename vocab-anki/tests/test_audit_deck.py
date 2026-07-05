"""Test audit_deck.py — card counting and issue detection.

Covers historical errors:
  - Hardcoded -1 meta exclusion undercounted decks without __META__ card
"""

import json
from unittest.mock import patch, MagicMock
import pytest

# Import the module under test
import sys
import os
_script_dir = os.path.dirname(os.path.abspath(__file__))
_package_dir = os.path.dirname(_script_dir)
_repo_root = os.path.dirname(_package_dir)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
_audit_script = os.path.join(_repo_root, "lib", "scripts", "audit_deck.py")

# Load audit_deck as a module
import importlib.util
_spec = importlib.util.spec_from_file_location("audit_deck", _audit_script)
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)


def _make_note(note_id, word, sentence, ipa="/test/", definition="[n.] test",
               translation="测试"):
    """Helper: build a minimal Anki note dict as returned by notesInfo."""
    return {
        "noteId": note_id,
        "fields": {
            "Word": {"value": word, "order": 0},
            "Sentence": {"value": sentence, "order": 1},
            "IPA": {"value": ipa, "order": 2},
            "DefinitionCN": {"value": definition, "order": 3},
            "TranslationCN": {"value": translation, "order": 4},
        },
    }


def _patch_ac(find_result, notes_result):
    """Mock AnkiConnect constructor to return a stub with fake methods."""
    mock_ac = MagicMock()
    mock_ac.find_notes_in_deck.return_value = find_result
    mock_ac.notes_info.return_value = notes_result
    return patch.object(_audit.AnkiConnect, "__new__", return_value=mock_ac)


# ── Card counting (the meta-count bug fix) ──


def test_total_without_meta_card():
    """No __META__ card: total should equal note count (bug: was -1)."""
    notes = [
        _make_note(1, "boa", "a <b>boa</b> constrictor"),
        _make_note(2, "ponder", "I <b>pondered</b> deeply"),
        _make_note(3, "devote", "and <b>devote</b> myself"),
    ]

    with _patch_ac([1, 2, 3], notes):
        result = _audit.audit_deck("Test Deck")

    assert result["total"] == 3, f"Expected 3, got {result['total']}"


def test_total_with_meta_card():
    """Deck with __META__ card: total should exclude it."""
    notes = [
        _make_note(1, "__META__", ""),
        _make_note(2, "boa", "a <b>boa</b> constrictor"),
        _make_note(3, "ponder", "I <b>pondered</b> deeply"),
        _make_note(4, "devote", "and <b>devote</b> myself"),
    ]

    with _patch_ac([1, 2, 3, 4], notes):
        result = _audit.audit_deck("Test Deck")

    assert result["total"] == 3, f"Expected 3, got {result['total']}"


def test_total_empty_deck():
    """Empty deck: total should be 0."""
    with _patch_ac([], []):
        result = _audit.audit_deck("Empty Deck")

    assert result == {}, "Empty deck should return empty dict"


def test_total_with_two_meta_cards():
    """Deck with 2 __META__ cards (edge case): both should be excluded."""
    notes = [
        _make_note(1, "__META__", ""),
        _make_note(2, "__META__", ""),
        _make_note(3, "boa", "a <b>boa</b> constrictor"),
        _make_note(4, "ponder", "I <b>pondered</b> deeply"),
    ]

    with _patch_ac([1, 2, 3, 4], notes):
        result = _audit.audit_deck("Test Deck")

    assert result["total"] == 2, f"Expected 2, got {result['total']}"


# ── Issue detection ──


def test_missing_ipa_detected():
    """Card with empty IPA should be flagged."""
    notes = [
        _make_note(1, "boa", "a <b>boa</b> constrictor", ipa=""),
    ]

    with _patch_ac([1], notes):
        result = _audit.audit_deck("Test Deck")

    assert "boa" in result["missing_ipa"]


def test_missing_definition_detected():
    """Card with short definition should be flagged."""
    notes = [
        _make_note(1, "boa", "a <b>boa</b> constrictor", definition=""),
    ]

    with _patch_ac([1], notes):
        result = _audit.audit_deck("Test Deck")

    assert "boa" in result["missing_def"]


def test_missing_translation_detected():
    """Card with empty translation should be flagged."""
    notes = [
        _make_note(1, "boa", "a <b>boa</b> constrictor", translation=""),
    ]

    with _patch_ac([1], notes):
        result = _audit.audit_deck("Test Deck")

    assert "boa" in result["missing_trans"]


def test_missing_trans_counted_in_combined_issues():
    """Missing translation should NOT be silently ignored when other issues exist."""
    notes = [
        _make_note(1, "boa", "a <b>boa</b> constrictor", ipa="", translation=""),
    ]

    with _patch_ac([1], notes):
        result = _audit.audit_deck("Test Deck")

    # Both issues should be present — missing_trans was historically
    # excluded from the issues count (line 139), making "All clear!"
    # falsely pass when only translations were missing.
    assert result["missing_ipa"] == ["boa"], "missing_ipa should be detected"
    assert result["missing_trans"] == ["boa"], "missing_trans should be detected"


def test_all_clear_no_issues():
    """Well-formed cards should produce no issues."""
    notes = [
        _make_note(1, "boa", "a <b>boa</b> constrictor"),
        _make_note(2, "ponder", "I <b>pondered</b> deeply"),
    ]

    with _patch_ac([1, 2], notes):
        result = _audit.audit_deck("Test Deck")

    assert result["total"] == 2
    assert result["lemma_mismatches"] == []
    assert result["missing_ipa"] == []
    assert result["missing_def"] == []
    assert result["missing_trans"] == []
