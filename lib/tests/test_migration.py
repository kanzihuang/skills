"""Integration tests for vocab-book deck migration and sync logic.

Mock AnkiConnect to test the full sync flow:
  1. First run → default bands, create sub-decks
  2. Second run → UUID reuse, 0 new words
  3. Band change → cards migrated to new sub-deck
  4. Invalid bands → parse_bands() error
  5. Dry-run → no Anki mutations
"""

import json
import sys
import os
from unittest.mock import patch, MagicMock, call

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.sync_anki import (
    sync,
    _derive_deck_name,
    _make_word_id,
    _compute_level_word_counts,
    _get_target_level_for_word,
    _build_subdeck_name,
)

# Import parse_bands for validation tests
sys.path.insert(0, os.path.join(_REPO_ROOT, "vocab-book"))
from filter_fulltext import parse_bands  # noqa: E402


# ── test fixtures ─────────────────────────────────────────────────────────────

def _make_word_entry(lemma: str, word: str, pos: str = "NOUN",
                     coca_level: int = 5, sentence: str = "A test sentence.",
                     definition_cn: str = "[n.] 测试",
                     translation_cn: str = "一个测试句子。",
                     target_offset: int = 2) -> dict:
    """Build a minimal word entry dict for testing."""
    return {
        "lemma": lemma,
        "word": word,
        "pos": pos,
        "coca_level": coca_level,
        "sentence": sentence,
        "definition_cn": definition_cn,
        "translation_cn": translation_cn,
        "target_offset": target_offset,
        "ipa": "/tɛst/",
    }


def _make_input_data(words: list[dict], suffix: str = "ab12cd34ef56",
                     title: str = "Test Book",
                     author: str = "Test Author",
                     bands: list[dict] | None = None,
                     is_bilateral: bool = False) -> dict:
    """Build minimal input data dict."""
    if bands is None:
        bands = [
            {"name": "COCA 1-3", "lo": 1, "hi": 3},
            {"name": "COCA 4-6", "lo": 4, "hi": 6},
            {"name": "COCA 7-9", "lo": 7, "hi": 9},
            {"name": "COCA 10", "lo": 10, "hi": 25},
        ]
    return {
        "book_title": title,
        "book_author": author,
        "suffix": suffix,
        "words": words,
        "bands": bands,
        "is_bilateral": is_bilateral,
    }


class MockAnkiConnect:
    """Simulates AnkiConnect responses for testing."""

    def __init__(self):
        self.decks: dict[str, list[int]] = {}      # deck_name → [note_id]
        self.notes: dict[int, dict] = {}            # note_id → note fields
        self.cards: dict[int, int] = {}             # card_id → note_id
        self.card_decks: dict[int, str] = {}        # card_id → deck_name
        self.next_note_id = 1000
        self.next_card_id = 2000
        self.media: dict[str, bytes] = {}
        self.added_notes: list[dict] = []
        self.deck_changes: list[tuple[list[int], str]] = []  # (card_ids, new_deck)
        self.ankiweb_synced = False

    # -- deck ops --
    def deck_names_and_ids(self):
        return {d: i + 1 for i, d in enumerate(self.decks)}

    def create_deck(self, name: str):
        if name not in self.decks:
            self.decks[name] = []

    def list_models(self):
        return ["Vocabulary Card (WeRead)"]

    def find_notes(self, query: str):
        # Parse simple deck:"X" queries
        result = []
        for deck_name, note_ids in self.decks.items():
            if f'deck:"{deck_name}"' in query or "deck:" not in query:
                result.extend(note_ids)
        return list(set(result))

    def notes_info(self, note_ids: list[int]):
        return [self.notes[nid] for nid in note_ids if nid in self.notes]

    def get_cards_of_notes(self, note_ids: list[int]):
        result = []
        for cid, nid in self.cards.items():
            if nid in note_ids:
                result.append(cid)
        return result

    def cards_info(self, cards: list[int]):
        result = []
        for cid in cards:
            nid = self.cards.get(cid)
            deck = self.card_decks.get(cid, "Default")
            result.append({"cardId": cid, "deckName": deck, "note": nid})
        return result

    def change_deck(self, card_ids: list[int], deck: str):
        self.deck_changes.append((card_ids, deck))
        return True

    def add_notes(self, notes: list[dict]):
        result = []
        for note in notes:
            nid = self.next_note_id
            self.next_note_id += 1
            self.added_notes.append(note)
            # Add note to mock deck
            deck_name = note.get("deckName", "Default")
            if deck_name not in self.decks:
                self.decks[deck_name] = []
            self.decks[deck_name].append(nid)
            # Store note info
            fields = {k: {"value": v, "order": 0}
                      for k, v in note.get("fields", {}).items()}
            cards_list = []
            # Create one card per note
            cid = self.next_card_id
            self.next_card_id += 1
            cards_list.append(cid)
            self.cards[cid] = nid
            self.card_decks[cid] = deck_name
            self.notes[nid] = {
                "noteId": nid,
                "fields": fields,
                "cards": cards_list,
            }
            result.append(nid)
        return result

    def sync(self):
        self.ankiweb_synced = True

    # -- methods needed by sync_anki.py --
    def find_deck_for_book_id(self, book_id: str):
        # Search all decks for notes with matching WordId suffix
        for deck_name, note_ids in self.decks.items():
            for nid in note_ids:
                if nid in self.notes:
                    wid = (self.notes[nid].get("fields", {})
                           .get("WordId", {}).get("value", ""))
                    if wid.endswith(f"_{book_id}"):
                        return deck_name, len(note_ids)
        return None, 0

    def find_notes_in_deck(self, deck_name: str):
        return self.decks.get(deck_name, [])

    def get_word_id_map(self, deck_name: str):
        result = {}
        for nid in self.decks.get(deck_name, []):
            if nid in self.notes:
                wid = (self.notes[nid].get("fields", {})
                       .get("WordId", {}).get("value", ""))
                if wid:
                    result[wid] = nid
        return result

    def get_word_id_map_with_deck(self, parent_deck: str):
        """Return {WordId: (note_id, deck_name)} across all sub-decks."""
        result = {}
        for deck_name, note_ids in self.decks.items():
            if deck_name == parent_deck or deck_name.startswith(parent_deck + "::"):
                for nid in note_ids:
                    if nid in self.notes:
                        wid = (self.notes[nid].get("fields", {})
                               .get("WordId", {}).get("value", ""))
                        if wid:
                            result[wid] = (nid, deck_name)
        return result

    def ensure_deck_and_model(self, deck_name: str, model_name: str = ""):
        if deck_name not in self.decks:
            self.decks[deck_name] = []
        return True


def _patch_ankiconnect(mock_ac: MockAnkiConnect):
    """Patch AnkiConnect() to return our mock."""
    return patch("lib.sync_anki.AnkiConnect", return_value=mock_ac)


# ── scenario 1: first run → default bands, create sub-decks ───────────────────

def test_first_run_creates_subdecks():
    """First run with default bands creates 4 sub-decks and adds cards."""
    words = [
        _make_word_entry("ponder", "pondered", coca_level=5),
        _make_word_entry("astray", "astray", coca_level=8, pos="ADV"),
    ]
    data = _make_input_data(words)
    mock_ac = MockAnkiConnect()

    with _patch_ankiconnect(mock_ac):
        result = sync(data, _derive_deck_name(data), no_audio=True)

    assert result["added"] == 2
    assert result["skipped"] == 0
    # Check that decks were created
    assert any("COCA 4-6" in d for d in mock_ac.decks)
    assert any("COCA 7-9" in d for d in mock_ac.decks)
    # Check notes were added with CocaLevel field
    assert len(mock_ac.added_notes) == 2
    for note in mock_ac.added_notes:
        assert "CocaLevel" in note["fields"]


# ── scenario 2: second run → UUID reuse, 0 new ───────────────────────────────

def test_second_run_all_dupes():
    """Second run with same UUID → all words already exist."""
    words = [
        _make_word_entry("ponder", "pondered", coca_level=5),
    ]
    data = _make_input_data(words)
    mock_ac = MockAnkiConnect()

    # First run
    with _patch_ankiconnect(mock_ac):
        sync(data, _derive_deck_name(data), no_audio=True)

    # Second run — same UUID → same WordIds
    words2 = [
        _make_word_entry("ponder", "pondered", coca_level=5),
    ]
    data2 = _make_input_data(words2)  # same suffix

    with _patch_ankiconnect(mock_ac):
        result = sync(data2, _derive_deck_name(data2), no_audio=True)

    assert result["added"] == 0
    assert result["skipped"] == 1


# ── scenario 3: band change → cards migrated ──────────────────────────────────

def test_band_change_migrates_cards():
    """Changing from default bands to a single bilateral band migrates cards."""
    words = [
        _make_word_entry("ponder", "pondered", coca_level=5),
        _make_word_entry("astray", "astray", coca_level=8, pos="ADV"),
    ]
    data = _make_input_data(words)
    mock_ac = MockAnkiConnect()

    # First run: default bands
    with _patch_ankiconnect(mock_ac):
        sync(data, _derive_deck_name(data), no_audio=True)

    # Second run: single bilateral band COCA 4-8
    words2 = [
        _make_word_entry("ponder", "pondered", coca_level=5),
        _make_word_entry("astray", "astray", coca_level=8, pos="ADV"),
    ]
    bands2 = [{"name": "COCA 4-8", "lo": 4, "hi": 8}]
    data2 = _make_input_data(words2, bands=bands2, is_bilateral=True)

    with _patch_ankiconnect(mock_ac):
        result = sync(data2, _derive_deck_name(data2), no_audio=True)

    assert result["added"] == 0  # already exist
    assert result["skipped"] == 2
    # Cards should have been migrated
    assert len(mock_ac.deck_changes) > 0


# ── scenario 4: invalid bands → parse_bands() error ───────────────────────────

def test_overlapping_bands_error():
    """Overlapping bands raise FilterError."""
    from filter_fulltext import FilterError
    with pytest.raises(FilterError, match="overlaps"):
        parse_bands("4-6,6-8")


def test_lo_greater_than_hi_error():
    """lo > hi raises FilterError."""
    from filter_fulltext import FilterError
    with pytest.raises(FilterError, match=r"lo\(6\) > hi\(4\)"):
        parse_bands("6-4")


def test_out_of_range_error():
    """Band out of 1-25 range raises FilterError."""
    from filter_fulltext import FilterError
    with pytest.raises(FilterError, match="out of COCA range"):
        parse_bands("3-30")


# ── scenario 5: dry-run → no mutations ────────────────────────────────────────

def test_dry_run_no_mutations():
    """Dry-run prints plan but does not mutate Anki."""
    words = [
        _make_word_entry("ponder", "pondered", coca_level=5),
    ]
    data = _make_input_data(words)
    mock_ac = MockAnkiConnect()

    with _patch_ankiconnect(mock_ac):
        result = sync(data, _derive_deck_name(data), no_audio=True, dry_run=True)

    assert result["added"] == len(words)
    assert len(mock_ac.added_notes) == 0  # no notes actually added
    assert len(mock_ac.deck_changes) == 0  # no cards moved


# ── helper function tests ─────────────────────────────────────────────────────

class TestComputeLevelWordCounts:
    def test_groups_by_coca_level(self):
        words = [
            _make_word_entry("a", "a", coca_level=3),
            _make_word_entry("b", "b", coca_level=3),
            _make_word_entry("c", "c", coca_level=5),
        ]
        counts = _compute_level_word_counts(words)
        assert counts == {3: 2, 5: 1}

    def test_ignores_invalid_levels(self):
        words = [
            _make_word_entry("a", "a", coca_level=3),
            {"lemma": "b", "word": "b", "pos": "NOUN"},  # no coca_level
        ]
        counts = _compute_level_word_counts(words)
        assert counts == {3: 1}


class TestGetTargetLevel:
    def test_valid_level(self):
        w = _make_word_entry("a", "a", coca_level=4)
        assert _get_target_level_for_word(w) == 4

    def test_invalid_level(self):
        w = {"lemma": "a", "word": "a", "coca_level": 30}
        assert _get_target_level_for_word(w) is None

    def test_missing_level(self):
        w = {"lemma": "a", "word": "a"}
        assert _get_target_level_for_word(w) is None


class TestBuildSubdeckName:
    def test_basic(self):
        band = {"name": "COCA 3-5", "lo": 3, "hi": 5}
        name = _build_subdeck_name("Parent", band)
        assert name == "Parent::COCA 3-5"

    def test_single_level(self):
        band = {"name": "COCA 10", "lo": 10, "hi": 25}
        name = _build_subdeck_name("Parent", band)
        assert name == "Parent::COCA 10"


class TestParseBands:
    def test_default_bands_when_none(self):
        bands, lo, hi, is_bilateral = parse_bands(None)
        assert is_bilateral is False
        assert lo == 1
        assert hi == 25
        assert len(bands) == 4

    def test_single_bilateral(self):
        bands, lo, hi, is_bilateral = parse_bands("3-10")
        assert is_bilateral is True
        assert lo == 3
        assert hi == 10
        assert bands == [(3, 10)]

    def test_multi_bilateral(self):
        bands, lo, hi, is_bilateral = parse_bands("3-5,6-8,9-10")
        assert is_bilateral is True
        assert lo == 3
        assert hi == 10
        assert bands == [(3, 5), (6, 8), (9, 10)]

    def test_single_sided_lower(self):
        bands, lo, hi, is_bilateral = parse_bands("3")
        assert is_bilateral is False
        assert lo == 3
        assert hi == 25

    def test_single_sided_upper(self):
        bands, lo, hi, is_bilateral = parse_bands("-10")
        assert is_bilateral is False
        assert lo == 1
        assert hi == 10
