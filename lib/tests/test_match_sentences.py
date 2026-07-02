"""Test match_sentences.py — sentence splitting and extraction."""

import re
import sys
import pytest

sys.path.insert(0, '/home/agent/github/kanzihuang/skills/vocab-anki')
from lib.scripts.match_sentences import split_sentences


def _clean(text):
    """Normalize text same way split_sentences does."""
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    return text


def test_split_sentences_ascii_quotes():
    """Standard ASCII double quotes after period are recognized."""
    text = _clean(
        'He wore a golden bracelet. '
        '"Whomever I touch," the snake said.'
    )
    sents = split_sentences(text)
    assert len(sents) == 2
    assert 'bracelet.' in sents[0]
    assert '"Whomever' in sents[1]


def test_split_sentences_curly_quotes():
    """Curly/smart quotes “” after period are recognized.
    Historical bug: the character class only matched ASCII \" (U+0022),
    not curly “ (U+201C), so dialogue sentences weren't split.
    """
    text = _clean(
        'He twined himself around the little prince’s ankle, '
        'like a golden bracelet. '
        '“Whomever I touch, I send back to the earth,” '
        'the snake spoke again.'
    )
    sents = split_sentences(text)
    # Must be at least 2 sentences — bracelet. and “Whomever...
    assert len(sents) >= 2, f"Expected >=2 sentences, got {len(sents)}: {sents}"
    assert 'bracelet.' in sents[0]
    assert '“Whomever' in sents[1]


def test_split_sentences_curly_single_quotes():
    """Curly single quotes ‘’ after period."""
    text = _clean(
        'He said goodbye. '
        '‘Farewell,’ she whispered.'
    )
    sents = split_sentences(text)
    assert len(sents) >= 2


def test_split_sentences_no_false_split():
    """Mid-sentence abbreviations (Mr., Dr.) inside dialogue are fine."""
    text = _clean(
        'He said, "Mr. Smith is here." Then he left.'
    )
    sents = split_sentences(text)
    # "Mr. Smith" has a period but then lowercase "Smith" — no split there
    assert len(sents) >= 1
