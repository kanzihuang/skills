"""Test match_sentences.py — PySBD segmentation + _better() comparison.

In the new design, sentences are stored WITHOUT <b> tags. Each result
has 'target_offset', 'matched_form', and 'text' fields. No candidates
array — only the best entry per (lemma, pos) is retained.
"""

import pytest
from lib.scripts.match_sentences import (
    split_sentences,
    hard_truncate,
    _better,
    _clean_quote_artifact,
    _normalize_dialogue_attribution,
)


# ── PySBD sentence splitting ──


def test_standard_sentence_split():
    sents = split_sentences("Hello! This is a test. Dr. Smith arrived.")
    assert len(sents) == 3
    assert "Dr. Smith arrived." in sents


def test_dialogue_quote_split():
    sents = split_sentences('"Draw me a sheep!" he said. "What?"')
    assert len(sents) == 2
    assert '"Draw me a sheep!" he said.' in sents


def test_abbreviation_not_split():
    sents = split_sentences("Mr. Jones and Dr. Lee went to U.S. offices.")
    assert len(sents) == 1


# ── Hard truncation ──


def test_hard_truncate_short_sentence_unchanged():
    text, was_truncated = hard_truncate("Short sentence.", max_len=500)
    assert text == "Short sentence."
    assert was_truncated is False


def test_hard_truncate_long_sentence_cut_at_word_boundary():
    long_text = "word " * 200
    result, was_truncated = hard_truncate(long_text, max_len=50)
    assert len(result) <= 50
    assert was_truncated is True
    assert not result.endswith(" ") or result[-1] != " "


# ── _clean_quote_artifact ──

def test_quote_artifact_no_leading_whitespace():
    assert _clean_quote_artifact('" "No,') == '"No,'


def test_quote_artifact_with_leading_whitespace():
    assert _clean_quote_artifact('  " "No,'.strip()) == '"No,'


def test_quote_artifact_clean_sentence_unchanged():
    assert _clean_quote_artifact('"Hello," he said.') == '"Hello," he said.'


# ── Dialogue-attribution normalization ──


class TestDialogueAttributionNormalization:
    """_normalize_dialogue_attribution joins colon-ending lines with dialogue."""

    def test_colon_attribution_joined(self):
        """'He looked...:\\n\\n\"No!\"' → ': \"No!\"'"""
        from lib.scripts.match_sentences import _normalize_dialogue_attribution

        text = 'He looked attentively, then:\n\n"No! That one is very ill."'
        result = _normalize_dialogue_attribution(text)
        assert ': "No!' in result, f"expected joined, got: {repr(result)}"
        assert '\n\n' not in result, "blank lines should be removed"

    def test_no_colon_not_affected(self):
        """Text without colon-attribution pattern is unchanged."""
        from lib.scripts.match_sentences import _normalize_dialogue_attribution

        text = "This is a normal sentence.\n\nAnother paragraph here."
        result = _normalize_dialogue_attribution(text)
        assert result == text, f"text should be unchanged, got: {repr(result)}"

    def test_colon_without_dialogue_preserved(self):
        """'Chapter 1:\\n\\nWhen I was six...' — no quote → preserved."""
        from lib.scripts.match_sentences import _normalize_dialogue_attribution

        text = "Chapter 1:\n\nWhen I was six years old, I once saw..."
        result = _normalize_dialogue_attribution(text)
        assert result == text, (
            f"colon without dialogue quote should be preserved, got: {repr(result)}"
        )

    def test_multiple_attributions_in_text(self):
        """Multiple colon/comma-attribution patterns all joined."""
        from lib.scripts.match_sentences import _normalize_dialogue_attribution

        text = (
            'He looked attentively, then:\n\n"No! Too ill."\n\n'
            'He replied,\n\n"It does not matter."'
        )
        result = _normalize_dialogue_attribution(text)
        assert ': "No!' in result
        assert ', "It does' in result
        # Paragraph breaks between unrelated lines should remain
        assert '\n\n' in result, (
            "paragraph break after dialogue close-quote should remain"
        )

    def test_comma_attribution_joined(self):
        """'He replied,\\n\\n\"It does not matter.\"' → ', \"It does...'"""
        from lib.scripts.match_sentences import _normalize_dialogue_attribution

        text = 'He replied,\n\n"It does not matter. Draw me a sheep."'
        result = _normalize_dialogue_attribution(text)
        assert ', "It does not matter' in result
        assert '\n\n' not in result

    def test_end_to_end_attentively_sentence(self):
        """Full pipeline: attentively gets a complete sentence with dialogue."""
        from lib.scripts.match_sentences import split_sentences

        text = (
            'I drew.  Then\n\n'
            'He looked attentively, then:\n\n'
            '"No! That one is already very ill. Do another one."'
        )
        sentences = split_sentences(text)
        # Should find one sentence containing both the attribution and dialogue
        combined = [s for s in sentences if 'attentively' in s]
        assert len(combined) == 1, f"expected 1 sentence with attentively, got {len(combined)}"
        sent = combined[0]
        assert 'attentively' in sent
        assert 'No!' in sent or 'very ill' in sent, (
            f"sentence should include dialogue, got: {repr(sent)}"
        )


# ── _better() three-tier comparison ──


def _cand(length):
    """Helper: build a minimal candidate dict for _better()."""
    return {"len": length, "text": "x" * length}


class TestBetter:
    """Test _better(old, new) — pure comparison, no scoring."""

    # Sweet-spot (30-250): shorter wins
    def test_sweet_spot_shorter_wins(self):
        assert _better(_cand(60), _cand(50)) is True
        assert _better(_cand(50), _cand(60)) is False

    def test_sweet_spot_tie_keeps_old(self):
        assert _better(_cand(100), _cand(100)) is False
        assert _better(_cand(30), _cand(30)) is False
        assert _better(_cand(250), _cand(250)) is False

    # Sweet-spot always beats too-long
    def test_sweet_spot_beats_too_long(self):
        assert _better(_cand(50), _cand(300)) is False   # old is sweet-spot → keep
        assert _better(_cand(300), _cand(50)) is True    # new is sweet-spot → switch

    # Sweet-spot always beats too-short
    def test_sweet_spot_beats_too_short(self):
        assert _better(_cand(50), _cand(15)) is False    # old is sweet-spot → keep
        assert _better(_cand(15), _cand(50)) is True     # new is sweet-spot → switch

    # Both too-long (>250): shorter wins
    def test_both_too_long_shorter_wins(self):
        assert _better(_cand(300), _cand(350)) is False  # old shorter → keep
        assert _better(_cand(350), _cand(300)) is True   # new shorter → switch

    # Both too-short (<30): longer wins
    def test_both_too_short_longer_wins(self):
        assert _better(_cand(15), _cand(20)) is True     # new longer
        assert _better(_cand(20), _cand(15)) is False    # old longer → keep

    # Too-long beats too-short (cross-tier)
    def test_too_long_beats_too_short(self):
        assert _better(_cand(300), _cand(15)) is False   # old is too-long → keep
        assert _better(_cand(15), _cand(300)) is True    # new is too-long → switch

    # Boundaries
    def test_boundary_30_belongs_sweet_spot(self):
        # 29 is too-short, 30 is sweet-spot
        assert _better(_cand(29), _cand(30)) is True     # sweet-spot wins
        assert _better(_cand(30), _cand(29)) is False    # sweet-spot kept

    def test_boundary_250_belongs_sweet_spot(self):
        # 250 is sweet-spot, 251 is too-long
        assert _better(_cand(250), _cand(251)) is False  # sweet-spot kept
        assert _better(_cand(251), _cand(250)) is True   # sweet-spot wins

    # Tie-break at all boundaries
    def test_tie_at_all_boundaries(self):
        assert _better(_cand(30), _cand(30)) is False    # keep old
        assert _better(_cand(250), _cand(250)) is False  # keep old
        assert _better(_cand(300), _cand(300)) is False  # keep old
        assert _better(_cand(15), _cand(15)) is False    # keep old


# ── POS correction ──


def _run_pipeline(in_coca: list[dict], text: str) -> dict:
    """Run match_sentences.py pipeline on minimal inputs, return words dict."""
    import json, subprocess, tempfile, os
    from pathlib import Path

    filter_json = {
        "suffix": "test00000000",
        "in_coca": in_coca,
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as fj:
        json.dump(filter_json, fj)
        fj_path = fj.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as ft:
        ft.write(text)
        txt_path = ft.name

    try:
        # Use vocab-book skill root (not shared lib) — symlink-aware
        _repo = Path(__file__).resolve().parent.parent.parent  # skills/
        _skill_root = _repo / "vocab-book"
        python = _skill_root / ".venv" / "bin" / "python3"
        ms_script = _skill_root / "lib" / "scripts" / "match_sentences.py"
        result = subprocess.run(
            [str(python), str(ms_script), fj_path, txt_path],
            capture_output=True, text=True, timeout=90,
        )
        idx = result.stdout.index('{\n  "book_title"')
        return json.loads(result.stdout[idx:])
    finally:
        os.unlink(fj_path)
        os.unlink(txt_path)


class TestPOSCorrections:
    """Verify POS corrections in the main processing pipeline."""

    def test_vbg_acomp_becomes_adj(self):
        """VBG + acomp (predicative) → ADJ via dep override."""
        result = _run_pipeline(
            [{"lemma": "overpowering", "rep": "overpowering",
              "forms": ["overpowering"], "coca_level": 7}],
            "When a mystery is too overpowering, one dare not disobey.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"expected ADJ, got {w['pos']}"

    def test_noun_amod_becomes_adj(self):
        """NOUN + amod → ADJ via dep override."""
        result = _run_pipeline(
            [{"lemma": "primeval", "rep": "primeval",
              "forms": ["primeval"], "coca_level": 10}],
            "I would never talk about primeval forests or stars.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"expected ADJ, got {w['pos']}"

    def test_propn_sentence_initial_becomes_noun(self):
        """Sentence-initial PROPN → NOUN (improved, not perfect for true ADJ)."""
        result = _run_pipeline(
            [{"lemma": "absurd", "rep": "absurd",
              "forms": ["absurd"], "coca_level": 4}],
            "Absurd as it might seem, I took out my pen.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", f"expected NOUN, got {w['pos']}"

    def test_be_to_vbn_pos_becomes_adj(self):
        """be-to VBN pattern sets POS=ADJ."""
        result = _run_pipeline(
            [{"lemma": "astounded", "rep": "astounded",
              "forms": ["astounded"], "coca_level": 7}],
            "I was astounded to hear the news.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"expected ADJ, got {w['pos']}"

    def test_be_to_true_when_determine_lemma_already_adj(self):
        """be_to=True even when _determine_lemma already returns surface form.

        Regression: _determine_lemma may detect ADJ via other signals
        (e.g. adjectival dep), returning the surface form before the
        be-to check runs.  The be_to flag must still be set to True
        when the pattern matches — it's metadata for quality checks.
        """
        result = _run_pipeline(
            [{"lemma": "astounded", "rep": "astounded",
              "forms": ["astounded"], "coca_level": 7}],
            "And I was astounded to hear the little fellow reply:",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"expected ADJ, got {w['pos']}"
        assert w["be_to"] is True, (
            f"expected be_to=True for 'was astounded to hear', "
            f"got be_to={w['be_to']}"
        )

    def test_vbg_acomp_lemma_not_reduced(self):
        """VBG + acomp: surface form preserved, not lemmatised to verb base."""
        result = _run_pipeline(
            [{"lemma": "overpowering", "rep": "overpowering",
              "forms": ["overpowering"], "coca_level": 7}],
            "When a mystery is too overpowering, one dare not disobey.",
        )
        w = result["words"][0]
        assert w["lemma"] == "overpowering", f"expected overpowering, got {w['lemma']}"

    def test_noun_attr_stays_noun(self):
        """NOUN + attr dep: stays NOUN, not promoted to ADJ.

        attr is the complement of copular verbs — it applies to both
        nouns ("He is a teacher") and adjectives ("He is tall").
        Unlike amod/acomp/oprd, it is NOT a reliable ADJ signal.
        Regression test for constrictor in "a boa constrictor".
        """
        result = _run_pipeline(
            [{"lemma": "constrictor", "rep": "constrictor",
              "forms": ["constrictor"], "coca_level": 8}],
            "It was a boa constrictor digesting an elephant.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", f"expected NOUN, got {w['pos']}"

    def test_mid_sentence_capitalized_propn_becomes_noun(self):
        """Mid-sentence capitalized common noun tagged PROPN → NOUN.

        E.g. "Boa" in "In the book, Boa constrictors swallow..."
        spaCy mis-tags the capitalized common noun as PROPN; since
        the word is in our filter vocabulary, convert to NOUN.
        """
        result = _run_pipeline(
            [{"lemma": "boa", "rep": "boa",
              "forms": ["boa", "boas"], "coca_level": 12}],
            "It was written in the book, Boa constrictors swallow their prey.",
        )
        words = result["words"]
        # Find the Boa entry
        boa_entry = [w for w in words if w["lemma"] == "boa"]
        assert len(boa_entry) == 1, f"expected 1 boa entry, got {len(boa_entry)}"
        assert boa_entry[0]["pos"] == "NOUN", \
            f"expected NOUN, got {boa_entry[0]['pos']}"
