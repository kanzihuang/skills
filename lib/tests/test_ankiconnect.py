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
