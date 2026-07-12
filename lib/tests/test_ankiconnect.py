"""Test ankiconnect.py — AnkiConnect JSON-RPC client with mocked HTTP.

Covers:
  - AnkiConnect._call() request/response
  - find_notes_in_deck, find_notes_by_field
  - notes_info, add_notes, store_media_file
  - AnkiConnectError propagation
"""

import json
import sys
from unittest.mock import patch, MagicMock

import pytest

import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.ankiconnect import AnkiConnect, AnkiConnectError


@pytest.fixture
def mock_requests():
    """Mock requests.post to return controlled JSON-RPC responses."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("lib.ankiconnect.requests.post", return_value=mock_response):
        yield mock_response


def _set_result(mock_resp, result):
    mock_resp.json.return_value = {"result": result, "error": None}


def _set_error(mock_resp, error_msg):
    mock_resp.json.return_value = {"result": None, "error": error_msg}


class TestAnkiConnectCall:
    def test_successful_call(self, mock_requests):
        _set_result(mock_requests, [1, 2, 3])
        ac = AnkiConnect()
        result = ac._call("findNotes", query="deck:Test")
        assert result == [1, 2, 3]

    def test_error_response(self, mock_requests):
        _set_error(mock_requests, "not found")
        ac = AnkiConnect()
        with pytest.raises(AnkiConnectError, match="not found"):
            ac._call("invalidAction")

    def test_connection_refused(self, mock_requests):
        import requests as req_mod
        with patch("lib.ankiconnect.requests.post") as mock_post:
            mock_post.side_effect = req_mod.ConnectionError("refused")
            ac = AnkiConnect()
            with pytest.raises(AnkiConnectError, match="Cannot reach"):
                ac._call("deckNames")

    def test_timeout(self, mock_requests):
        import requests as req_mod
        with patch("lib.ankiconnect.requests.post") as mock_post:
            mock_post.side_effect = req_mod.Timeout("timed out")
            ac = AnkiConnect()
            with pytest.raises(AnkiConnectError, match="timed out"):
                ac._call("deckNames")


class TestFindNotes:
    def test_find_notes_in_deck(self, mock_requests):
        _set_result(mock_requests, [100, 200])
        ac = AnkiConnect()
        assert ac.find_notes_in_deck("My Deck") == [100, 200]

    def test_find_notes_by_field(self, mock_requests):
        _set_result(mock_requests, [300])
        ac = AnkiConnect()
        result = ac.find_notes_by_field("My Deck", "WordId", "*_22720170")
        assert result == [300]
        # Verify correct Anki search syntax: field:value without outer quotes
        from lib.ankiconnect import requests as ankiconnect_req
        payload = ankiconnect_req.post.call_args[1]["json"]["params"]["query"]
        assert "WordId:*_22720170" in payload
        assert '"WordId:*_22720170"' not in payload, (
            "outer quotes break Anki field search syntax"
        )

    def test_find_notes_by_field_no_deck(self, mock_requests):
        """Query without deck name must also use unquoted field:value syntax."""
        _set_result(mock_requests, [400])
        ac = AnkiConnect()
        result = ac.find_notes_by_field("", "WordId", "*_22720170")
        assert result == [400]
        from lib.ankiconnect import requests as ankiconnect_req
        payload = ankiconnect_req.post.call_args[1]["json"]["params"]["query"]
        assert payload == "WordId:*_22720170", (
            f"expected 'WordId:*_22720170' (no outer quotes), got {payload!r}"
        )

    def test_empty_deck(self, mock_requests):
        _set_result(mock_requests, [])
        ac = AnkiConnect()
        assert ac.find_notes_in_deck("Empty Deck") == []


class TestNotesInfo:
    def test_notes_info(self, mock_requests):
        _set_result(mock_requests, [{
            "noteId": 1,
            "fields": {
                "Word": {"value": "test", "order": 0},
                "WordId": {"value": "test_123", "order": 1},
            },
            "tags": [],
        }])
        ac = AnkiConnect()
        info = ac.notes_info([1])
        assert len(info) == 1
        assert info[0]["fields"]["Word"]["value"] == "test"


class TestAddNotes:
    def test_add_notes_success(self, mock_requests):
        _set_result(mock_requests, [1783200000001, 1783200000002])
        ac = AnkiConnect()
        notes = [
            {"deckName": "Test", "modelName": "Basic", "fields": {}},
            {"deckName": "Test", "modelName": "Basic", "fields": {}},
        ]
        result = ac.add_notes(notes)
        assert result == [1783200000001, 1783200000002]

    def test_add_notes_duplicate_fallback(self, mock_requests):
        """Batch fails with duplicate → retry individually via addNote."""
        from lib.ankiconnect import AnkiConnectError

        ac = AnkiConnect()
        notes = [
            {"deckName": "Test", "modelName": "Basic", "fields": {"Word": "dup"}},
            {"deckName": "Test", "modelName": "Basic", "fields": {"Word": "ok"}},
        ]

        # Patch _call to simulate batch failure then individual success/failure
        with patch.object(ac, "_call") as mock_call:
            # Batch: raises duplicate error
            # Individual: note 0 fails, note 1 succeeds
            mock_call.side_effect = [
                AnkiConnectError("cannot create note because it is a duplicate"),
                AnkiConnectError("duplicate"),   # note 0: dup → None
                1783200000002,                   # note 1: OK
            ]
            result = ac.add_notes(notes)
            assert result == [None, 1783200000002]

        # Batch call should have been made
        mock_call.assert_any_call("addNotes", notes=notes)
        # Individual call for note 1 should have been made
        mock_call.assert_any_call("addNote", note=notes[1])


class TestStoreMedia:
    def test_store_media_file(self, mock_requests):
        _set_result(mock_requests, "test.mp3")
        ac = AnkiConnect()
        assert ac.store_media_file("test.mp3", b"fake audio") == "test.mp3"

    def test_store_media_base64(self, mock_requests):
        _set_result(mock_requests, "word.mp3")
        ac = AnkiConnect()
        assert ac.store_media_file("word.mp3", b"\x00\x01\x02") == "word.mp3"


class TestFindDeckForBookId:
    """find_deck_for_book_id() — deck name resolution by bookId."""

    def test_no_existing_cards(self, mock_requests):
        """Returns (None, 0) when no notes match the bookId."""
        # findNotes returns empty list
        mock_requests.json.return_value = {
            "result": [], "error": None
        }
        ac = AnkiConnect()
        deck, count = ac.find_deck_for_book_id("22720170")
        assert deck is None
        assert count == 0

    def test_cards_found_with_valid_deck(self, mock_requests):
        """Returns (deck_name, count) when matching cards exist."""
        # The method makes 3 calls: findNotes, findCards, cardsInfo.
        # Mock side_effect to return different values per call.
        mock_requests.json.side_effect = [
            {"result": [100, 101, 102], "error": None},   # findNotes → 3 notes
            {"result": [200], "error": None},               # findCards → card IDs
            {"result": [{"deckName": "My Book (Author)", "note": 100}], "error": None},  # cardsInfo
        ]
        ac = AnkiConnect()
        deck, count = ac.find_deck_for_book_id("12345")
        assert deck == "My Book (Author)"
        assert count == 3

    def test_cards_found_but_no_card_ids(self, mock_requests):
        """Returns (None, count) when notes exist but card lookup fails."""
        mock_requests.json.side_effect = [
            {"result": [300, 301], "error": None},  # findNotes → 2 notes
            {"result": [], "error": None},            # findCards → empty
        ]
        ac = AnkiConnect()
        deck, count = ac.find_deck_for_book_id("99999")
        assert deck is None
        assert count == 2

    def test_anki_connect_error(self, mock_requests):
        """Returns (None, 0) when AnkiConnect returns an error."""
        mock_requests.json.return_value = {
            "result": None, "error": "connection refused"
        }
        ac = AnkiConnect()
        deck, count = ac.find_deck_for_book_id("22720170")
        assert deck is None
        assert count == 0


class TestChangeDeck:
    """change_deck() — move cards between decks."""

    def test_move_cards_to_new_deck(self, mock_requests):
        _set_result(mock_requests, True)
        ac = AnkiConnect()
        assert ac.change_deck([100, 200], "Parent::COCA 4") is True


class TestGetWordIdMapWithDeck:
    """get_word_id_map_with_deck() — {WordId: (note_id, deck)} for all sub-decks."""

    def test_empty_deck(self, mock_requests):
        """Returns {} when no notes found."""
        _set_result(mock_requests, [])  # findNotes → []
        ac = AnkiConnect()
        result = ac.get_word_id_map_with_deck("My Book - 分级词汇")
        assert result == {}

    def test_returns_word_id_to_note_and_deck(self, mock_requests):
        """Returns {WordId: (note_id, deck_name)} across sub-decks."""
        mock_requests.json.side_effect = [
            # findNotes → 2 notes
            {"result": [1001, 1002], "error": None},
            # notesInfo → 2 notes
            {"result": [
                {
                    "noteId": 1001,
                    "cards": [2001, 2002],
                    "fields": {"WordId": {"value": "ponder_VERB_a1b2c3d4e5f6"}},
                },
                {
                    "noteId": 1002,
                    "cards": [2003],
                    "fields": {"WordId": {"value": "astray_ADJ_a1b2c3d4e5f6"}},
                },
            ], "error": None},
            # cardsInfo → deck names for each card
            {"result": [
                {"cardId": 2001, "deckName": "Parent::COCA 4 (12 words)", "note": 1001},
                {"cardId": 2002, "deckName": "Parent::COCA 4 (12 words)", "note": 1001},
                {"cardId": 2003, "deckName": "Parent::COCA 5 (3 words)", "note": 1002},
            ], "error": None},
        ]
        ac = AnkiConnect()
        result = ac.get_word_id_map_with_deck("Parent")
        assert result == {
            "ponder_VERB_a1b2c3d4e5f6": (1001, "Parent::COCA 4 (12 words)"),
            "astray_ADJ_a1b2c3d4e5f6": (1002, "Parent::COCA 5 (3 words)"),
        }

    def test_skips_notes_without_word_id(self, mock_requests):
        """Notes missing WordId are silently skipped."""
        mock_requests.json.side_effect = [
            {"result": [3001], "error": None},
            {"result": [{
                "noteId": 3001,
                "cards": [4001],
                "fields": {},  # no WordId field
            }], "error": None},
            {"result": [
                {"cardId": 4001, "deckName": "Parent", "note": 3001},
            ], "error": None},
        ]
        ac = AnkiConnect()
        result = ac.get_word_id_map_with_deck("Parent")
        assert result == {}


class TestFindVocabBookSuffix:
    """find_vocab_book_suffix() — extract UUID from existing deck."""

    def test_no_matching_deck(self, mock_requests):
        """Returns (None, None) when no vocab-book deck exists."""
        _set_result(mock_requests, {"Other Deck": 1})
        ac = AnkiConnect()
        deck, suffix = ac.find_vocab_book_suffix("The Little Prince",
                                                   "Antoine de Saint-Exupery")
        assert deck is None
        assert suffix is None

    def test_extracts_suffix_from_cards(self, mock_requests):
        """Finds the deck and extracts 12-char hex suffix from WordId."""
        mock_requests.json.side_effect = [
            # deckNamesAndIds
            {"result": {
                "Little Prince (Antoine de Saint-Exupery) - 分级词汇": 1,
                "Other": 2,
            }, "error": None},
            # findNotes
            {"result": [5001, 5002], "error": None},
            # notesInfo
            {"result": [{
                "noteId": 5001,
                "fields": {"WordId": {"value": "ponder_VERB_ab12cd34ef56"}},
            }], "error": None},
        ]
        ac = AnkiConnect()
        deck, suffix = ac.find_vocab_book_suffix(
            "Little Prince", "Antoine de Saint-Exupery"
        )
        assert deck == "Little Prince (Antoine de Saint-Exupery) - 分级词汇"
        assert suffix == "ab12cd34ef56"

    def test_no_cards_in_deck(self, mock_requests):
        """Returns (None, None) when deck exists but has no cards."""
        mock_requests.json.side_effect = [
            {"result": {"Empty Book (Author) - 分级词汇": 1}, "error": None},
            {"result": [], "error": None},  # findNotes → empty
        ]
        ac = AnkiConnect()
        deck, suffix = ac.find_vocab_book_suffix("Empty Book", "Author")
        assert deck is None
        assert suffix is None

    def test_suffix_not_hex(self, mock_requests):
        """Returns (None, None) when suffix is not 12 valid hex chars."""
        mock_requests.json.side_effect = [
            {"result": {"Weird Book (Author) - 分级词汇": 1}, "error": None},
            {"result": [6001], "error": None},
            {"result": [{
                "noteId": 6001,
                "fields": {"WordId": {"value": "word_NOUN_short"}},
            }], "error": None},
        ]
        ac = AnkiConnect()
        deck, suffix = ac.find_vocab_book_suffix("Weird Book", "Author")
        assert deck is None
        assert suffix is None

    def test_anki_connect_error(self, mock_requests):
        """Returns (None, None) on AnkiConnectError (graceful degradation)."""
        mock_requests.json.return_value = {
            "result": None, "error": "connection refused"
        }
        ac = AnkiConnect()
        deck, suffix = ac.find_vocab_book_suffix("Any Book", "Author")
        assert deck is None
        assert suffix is None
