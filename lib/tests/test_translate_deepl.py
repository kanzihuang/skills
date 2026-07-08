"""Test translate_deepl.py — DeepL translation with mocked API.

Covers:
  - strip_tags() for <b> removal
  - _build_sentence_regex() fuzzy matching
  - translate_batch() API call + error handling
"""

import json
import sys
from unittest.mock import patch, MagicMock

import pytest

# Add repo root for lib imports
import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib.scripts.translate_deepl import (
    strip_tags,
    translate_batch,
)
from lib.utils import build_sentence_regex as _build_sentence_regex


class TestStripTags:
    def test_strips_b_tags(self):
        assert strip_tags("He <b>sputtered</b> a little.") == "He sputtered a little."

    def test_no_tags_unchanged(self):
        assert strip_tags("Hello world.") == "Hello world."

    def test_multiple_tags(self):
        assert strip_tags("<b>Clad</b> in <b>ermine</b>.") == "Clad in ermine."

    def test_empty(self):
        assert strip_tags("") == ""


class TestBuildSentenceRegex:
    def test_simple(self):
        pattern = _build_sentence_regex("He sputtered a little")
        import re
        assert re.search(pattern, "He sputtered a little, and seemed vexed.")

    def test_punctuation_stripped(self):
        pattern = _build_sentence_regex('"I do not permit insubordination."')
        import re
        assert re.search(pattern, "I do not permit insubordination.")

    def test_newline_handling(self):
        pattern = _build_sentence_regex("he was seated upon a throne")
        import re
        assert re.search(pattern, "he was seated upon a\nthrone")


class TestTranslateBatch:
    def test_success(self):
        mock_translator = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "他结结巴巴地说了一会儿。"
        mock_translator.translate_text.return_value = [mock_result]

        with patch("lib.scripts.translate_deepl.translator", mock_translator):
            results = translate_batch(["He sputtered a little."])
            assert len(results) == 1
            assert "结结巴巴" in results[0]

    def test_with_context(self):
        mock_translator = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "测试翻译"
        mock_translator.translate_text.return_value = [mock_result]

        with patch("lib.scripts.translate_deepl.translator", mock_translator):
            results = translate_batch(["test sentence"], context="surrounding text")
            # Context should be passed to DeepL
            call_kwargs = mock_translator.translate_text.call_args[1]
            assert call_kwargs["target_lang"] == "ZH"
            assert call_kwargs["context"] == "surrounding text"

    def test_api_error(self):
        import deepl
        mock_translator = MagicMock()
        mock_translator.translate_text.side_effect = deepl.DeepLException("quota exceeded")

        with patch("lib.scripts.translate_deepl.translator", mock_translator):
            with pytest.raises(deepl.DeepLException):
                translate_batch(["test"])
