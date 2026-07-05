"""Test sync_anki.py sync() orchestration with mocked AnkiConnect.

Covers:
  - build_note_entry() note construction
  - sync() with empty/new words
  - parse_args() CLI parsing
"""

import json
import sys
import tempfile
import os
from unittest.mock import patch

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _build_word(word, definition="[n.] test", ipa="/tɛst/",
                sentence="This is a <b>test</b>.", translation="这是测试。"):
    return {
        "word": word,
        "lemma": "",
        "ipa": ipa,
        "definition_cn": definition,
        "sentence": sentence,
        "translation_cn": translation,
        "forms": [word],
    }


def _build_input(words, book_id="12345678", deck_name="Test Deck"):
    return {
        "book_title": "Test Book",
        "book_author": "Test Author",
        "deck_name": deck_name,
        "book_id": book_id,
        "words": words,
    }


class TestParseArgs:
    def test_defaults(self):
        from lib.sync_anki import parse_args
        with patch("sys.argv", ["sync_anki.py", "input.json"]):
            args = parse_args()
            assert args.input_file == "input.json"
            assert not args.dry_run
            assert not args.no_audio

    def test_dry_run(self):
        from lib.sync_anki import parse_args
        with patch("sys.argv", ["sync_anki.py", "input.json", "--dry-run"]):
            assert parse_args().dry_run

    def test_deck_and_no_audio(self):
        from lib.sync_anki import parse_args
        with patch("sys.argv", ["sync_anki.py", "in.json", "--deck", "My Deck", "--no-audio"]):
            args = parse_args()
            assert args.deck == "My Deck"
            assert args.no_audio


class TestBuildNoteEntry:
    def test_basic_entry(self):
        from lib.sync_anki import build_note_entry
        word = _build_word("test", definition="[n.] 测试", ipa="/tɛst/",
                           sentence="A <b>test</b> sentence.",
                           translation="一个测试句子。")
        note = build_note_entry(word, ipa="/tɛst/", book_id="12345678")
        assert note["modelName"] == "Vocabulary Card (WeRead)"
        assert note["fields"]["Word"] == "test"
        assert "test_12345678" in note["fields"]["WordId"]
        assert "/tɛst/" == note["fields"]["IPA"]
        assert "测试" in note["fields"]["DefinitionCN"]

    def test_lemma_in_word_id(self):
        from lib.sync_anki import build_note_entry
        word = _build_word("vexed", definition="[adj.] 恼怒的", ipa="/vɛkst/",
                           sentence="He seemed <b>vexed</b>.",
                           translation="他看起来很恼怒。")
        word["lemma"] = "vexed"
        note = build_note_entry(word, ipa="/vɛkst/", book_id="12345678", lemma="vexed")
        assert "vexed_12345678" in note["fields"]["WordId"]

    def test_word_id_uses_safe_filename(self):
        from lib.sync_anki import build_note_entry
        word = _build_word("don't", definition="[v.] 不", ipa="/doʊnt/",
                           sentence="I <b>don't</b> know.",
                           translation="我不知道。")
        note = build_note_entry(word, ipa="/doʊnt/", book_id="12345678")
        assert "don_t_12345678" in note["fields"]["WordId"]

    def test_make_word_id_with_suffix(self):
        """_make_word_id should work with suffix as namespace."""
        from lib.sync_anki import _make_word_id
        word = _build_word("test")
        wid = _make_word_id(word, "a1b2c3d4e5f6")
        assert wid == "test_a1b2c3d4e5f6"


class TestSyncEmpty:
    def test_empty_words(self):
        """sync() with empty word list returns error."""
        from lib.sync_anki import sync
        result = sync(_build_input([]), deck_name="Test", dry_run=True, no_audio=True)
        assert result is not None
        assert result.get("words_skipped") is not None or result.get("error") is not None

    def test_sync_accepts_suffix_instead_of_book_id(self):
        """sync() should work when input has 'suffix' but no 'book_id'."""
        from lib.sync_anki import sync
        data = _build_input([])
        del data["book_id"]
        data["suffix"] = "a1b2c3d4e5f6"
        result = sync(data, deck_name="Test", dry_run=True, no_audio=True)
        assert result is not None


class TestDeriveDeckName:
    """Deck name auto-derivation from input JSON."""

    def test_vocab_anki_flat_deck(self):
        """vocab-anki (book_id, no suffix): plain '{Title} ({Author})'."""
        from lib.sync_anki import _derive_deck_name
        data = {
            "book_title": "Test Book",
            "book_author": "Test Author",
            "book_id": "12345678",
        }
        assert _derive_deck_name(data) == "Test Book (Test Author)"

    def test_vocab_book_suffix_appends_graded(self):
        """vocab-book (suffix, no book_id): appends ' - 分级词汇'."""
        from lib.sync_anki import _derive_deck_name
        data = {
            "book_title": "Test Book",
            "book_author": "Test Author",
            "suffix": "a1b2c3d4e5f6",
        }
        result = _derive_deck_name(data)
        assert result == "Test Book (Test Author) - 分级词汇"

    def test_vocab_book_no_author(self):
        """vocab-book without author: '{Title} Vocabulary - 分级词汇'."""
        from lib.sync_anki import _derive_deck_name
        data = {
            "book_title": "Test Book",
            "suffix": "a1b2c3d4e5f6",
        }
        result = _derive_deck_name(data)
        assert result == "Test Book Vocabulary - 分级词汇"

    def test_both_book_id_and_suffix_present(self):
        """book_id takes priority — no ' - 分级词汇' suffix."""
        from lib.sync_anki import _derive_deck_name
        data = {
            "book_title": "Test Book",
            "book_author": "Test Author",
            "book_id": "12345678",
            "suffix": "a1b2c3d4e5f6",
        }
        assert _derive_deck_name(data) == "Test Book (Test Author)"

    def test_json_deck_name_priority(self):
        """JSON deck_name field takes highest priority."""
        from lib.sync_anki import _derive_deck_name
        data = {
            "book_title": "Test Book",
            "deck_name": "Custom Deck Name",
            "suffix": "a1b2c3d4e5f6",
        }
        assert _derive_deck_name(data) == "Custom Deck Name"

    def test_cli_deck_override(self):
        """--deck CLI flag overrides auto-derive."""
        from lib.sync_anki import _derive_deck_name
        data = {
            "book_title": "Test Book",
            "book_author": "Test Author",
            "suffix": "a1b2c3d4e5f6",
        }
        assert _derive_deck_name(data, cli_deck="CLI Deck") == "CLI Deck"

    def test_json_deck_beats_cli(self):
        """JSON deck_name beats CLI deck."""
        from lib.sync_anki import _derive_deck_name
        data = {
            "book_title": "Test Book",
            "deck_name": "JSON Deck",
        }
        assert _derive_deck_name(data, cli_deck="CLI Deck") == "JSON Deck"
