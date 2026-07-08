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
    _cmu_ipa,
    _clean_quote_artifact,
    _normalize_dialogue_attribution,
    _first_word_boundary_offset,
    _is_fragment,
)
from lib.scripts.check_step_completed import _has_sentence_ending


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


def test_double_space_normalized():
    """split_sentences collapses multiple consecutive spaces into one."""
    sents = split_sentences("This is  a  test  sentence.")
    assert len(sents) == 1
    assert "  " not in sents[0]
    assert sents[0] == "This is a test sentence."


def test_triple_space_normalized():
    sents = split_sentences("Hello   world.")
    assert "   " not in sents[0]
    assert sents[0] == "Hello world."


def test_hyphen_space_preserved():
    """split_sentences does NOT fix hyphen-space (known limitation).
    Cannot reliably distinguish OCR error 'fair-to- middling' from
    legitimate 're- enter'."""
    sents = split_sentences("fair-to- middling quality.")
    assert len(sents) == 1
    assert "to- middling" in sents[0]


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

    def test_curly_quote_attribution_joined(self):
        """Curly quotes '“' / '”' are joined like ASCII quotes."""
        from lib.scripts.match_sentences import _normalize_dialogue_attribution

        text = 'He replied,\n\n“It does not matter.”'
        result = _normalize_dialogue_attribution(text)
        assert ', “It does' in result or ', "It does' in result, (
            f"curly-quote attribution should be joined, got: {repr(result)}"
        )
        assert '\n\n' not in result, "blank lines should be removed"

    def test_triple_newline_attribution_joined(self):
        """3+ consecutive newlines are collapsed and attribution joined."""
        from lib.scripts.match_sentences import _normalize_dialogue_attribution

        text = 'He replied,\n\n\n"It does not matter."'
        result = _normalize_dialogue_attribution(text)
        assert ', "It does' in result, (
            f"triple-newline attribution should be joined, got: {repr(result)}"
        )
        assert '\n\n\n' not in result, "triple newlines should be removed"

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


def _cand(length, is_fragment=False):
    """Helper: build a minimal candidate dict for _better()."""
    return {"len": length, "text": "x" * length, "is_fragment": is_fragment}


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

    def test_better_uses_config_constants(self):
        """Verify _better references MIN_SENTENCE_LENGTH, not hardcoded 30."""
        import inspect
        source = inspect.getsource(_better)
        assert "MIN_SENTENCE_LENGTH" in source, \
            "_better() must use MIN_SENTENCE_LENGTH from config"

    # Tier 0: complete sentence always beats fragment
    def test_complete_beats_fragment(self):
        assert _better(
            _cand(50, is_fragment=True),
            _cand(50, is_fragment=False),
        ) is True   # new is complete → switch

    def test_fragment_does_not_beat_complete(self):
        assert _better(
            _cand(50, is_fragment=False),
            _cand(50, is_fragment=True),
        ) is False  # old is complete → keep

    def test_complete_too_long_beats_fragment_sweet_spot(self):
        """Even a too-long complete sentence beats a sweet-spot fragment."""
        assert _better(
            _cand(50, is_fragment=True),
            _cand(300, is_fragment=False),
        ) is True   # new is complete (even though too-long) → switch

    def test_fragment_sweet_spot_does_not_beat_complete_too_short(self):
        """A sweet-spot fragment does NOT beat a too-short complete sentence."""
        assert _better(
            _cand(15, is_fragment=False),
            _cand(50, is_fragment=True),
        ) is False  # old is complete → keep

    def test_both_fragments_fall_through_to_length(self):
        """Both fragments → fall through to Tier 1-3 length comparison."""
        assert _better(
            _cand(60, is_fragment=True),
            _cand(50, is_fragment=True),
        ) is True   # new shorter → sweet-spot rule

    def test_both_complete_unchanged_behavior(self):
        """Both complete → existing length comparison unchanged."""
        assert _better(
            _cand(60, is_fragment=False),
            _cand(50, is_fragment=False),
        ) is True   # new shorter → sweet-spot rule


# ── cmudict IPA fallback for derived forms (Issue 3) ──


class TestCmuIpaFallback:
    """Test _cmu_ipa suffix-stripping fallback for -ly adverbs etc."""

    def test_direct_cmu_lookup_still_works(self):
        """Words directly in cmudict are unchanged."""
        result = _cmu_ipa("hello")
        assert result == "/həˈloʊ/", f"Expected /həˈloʊ/, got: {result}"

    def test_ly_adverb_fallback(self):
        """indulgently → fall back to indulgent + /li/."""
        result = _cmu_ipa("indulgently")
        assert result, f"Expected non-empty IPA for indulgently"
        assert result.endswith("li/"), \
            f"Expected /li/ suffix on fallback IPA, got: {result}"

    def test_unknown_word_returns_empty(self):
        """Non-dictionary word with no suffix match returns empty string."""
        result = _cmu_ipa("xyzzy123")
        assert result == "", f"Expected empty string, got: {result}"


# ── _is_fragment detection ──


class TestIsFragment:
    """Test _is_fragment() — sentence completeness detection."""

    # Signal 1: no sentence-ending punctuation after stripping quotes
    def test_complete_sentence_is_not_fragment(self):
        assert _is_fragment("This is a complete sentence.") is False

    def test_question_is_not_fragment(self):
        assert _is_fragment("Is this a question?") is False

    def test_exclamation_is_not_fragment(self):
        assert _is_fragment("What a pretty house!") is False

    def test_missing_period_is_fragment(self):
        assert _is_fragment("This sentence has no ending") is True

    def test_quote_ending_stripped_then_punctuation(self):
        assert _is_fragment("He said, 'Hello.'") is False

    def test_quote_ending_stripped_no_punctuation(self):
        assert _is_fragment('"Once upon a time there was a prince') is True

    # Signal 2: odd number of ASCII double quotes
    def test_unclosed_double_quote_is_fragment(self):
        assert _is_fragment('He said, "hello') is True

    def test_balanced_double_quotes_not_fragment(self):
        assert _is_fragment('He said, "hello."') is False

    def test_three_quotes_is_fragment(self):
        assert _is_fragment('He said, "hello," then "goodbye') is True

    # Signal 3: starts with lowercase
    def test_starts_lowercase_is_fragment(self):
        assert _is_fragment("than himself, and who had need of a sheep...") is True

    def test_starts_capital_is_not_fragment(self):
        assert _is_fragment("Than himself, and who had need.") is False

    # Edge cases
    def test_empty_string_is_fragment(self):
        assert _is_fragment("") is True

    def test_whitespace_only_is_fragment(self):
        assert _is_fragment("   ") is True


# ── POS correction ──


def _run_pipeline(in_coca: list[dict], text: str, extra_args: list[str] | None = None) -> dict:
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
        cmd = [str(python), str(ms_script), fj_path, txt_path]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(
            cmd,
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
        """Sentence-initial PROPN → NOUN (standard case, not inverted ADJ)."""
        result = _run_pipeline(
            [{"lemma": "desert", "rep": "desert",
              "forms": ["desert"], "coca_level": 5}],
            "Desert stretched before them for miles.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", f"expected NOUN, got {w['pos']}"

    def test_inverted_adj_sentence_initial_becomes_adj(self):
        """Sentence-initial inverted ADJ 'Absurd as it might seem' → ADJ."""
        result = _run_pipeline(
            [{"lemma": "absurd", "rep": "absurd",
              "forms": ["absurd"], "coca_level": 4}],
            "Absurd as it might seem to me, I took out of my pocket a sheet of paper and my fountain-pen.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"expected ADJ, got {w['pos']}"

    def test_inverted_adj_king_as_he_was_stays_propn(self):
        """'King as he was' (npadvmod) → NOT converted to ADJ.

        'King' is a noun acting as npadvmod, not an inverted adjective in advcl.
        The dep guard prevents false positives for npadvmod-tagged tokens.
        """
        result = _run_pipeline(
            [{"lemma": "king", "rep": "king",
              "forms": ["king"], "coca_level": 2}],  # L2 would normally be excluded
            "King as he was, he had no real power.",
        )
        # 'king' is L2, likely not in COCA filter for real use,
        # but if it passed through, it should stay NOUN (spaCy tags as PROPN→NOUN)
        # or be excluded entirely
        words = result.get("words", [])
        king_entries = [w for w in words if w["lemma"] == "king"]
        if king_entries:
            assert king_entries[0]["pos"] != "ADJ", \
                f"King should NOT be ADJ, got {king_entries[0]['pos']}"

    def test_conj_pos_inheritance_adjective_in_noun_list(self):
        """'arithmetic' tagged ADJ in noun coordination → inherits NOUN from root."""
        result = _run_pipeline(
            [{"lemma": "arithmetic", "rep": "arithmetic",
              "forms": ["arithmetic"], "coca_level": 7}],
            "My studies had been concentrated on geography, history, arithmetic and grammar.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", f"expected NOUN, got {w['pos']}"

    def test_conj_pos_inheritance_chain_walks_to_root(self):
        """Chain-walking: conjunct's head is also conjunct → walk to root."""
        result = _run_pipeline(
            [{"lemma": "arithmetic", "rep": "arithmetic",
              "forms": ["arithmetic"], "coca_level": 7}],
            "We studied geography, history, arithmetic and grammar.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", f"expected NOUN, got {w['pos']}"

    def test_conj_pos_inheritance_same_pos_no_change(self):
        """ADJ-conj-ADJ: 'blue' in 'red and blue' — no change needed."""
        result = _run_pipeline(
            [{"lemma": "blue", "rep": "blue",
              "forms": ["blue"], "coca_level": 1}],
            "The red and blue flag waved.",
        )
        # blue is L1, likely excluded, but if it passes:
        words = result.get("words", [])
        blue_entries = [w for w in words if w["lemma"] == "blue"]
        if blue_entries:
            assert blue_entries[0]["pos"] == "ADJ", \
                f"blue should stay ADJ, got {blue_entries[0]['pos']}"

    def test_conj_pos_inheritance_propn_not_converted(self):
        """'Jerry' conj of 'Tom' (PROPN) — stays PROPN, not inherited."""
        result = _run_pipeline(
            [{"lemma": "jerry", "rep": "jerry",
              "forms": ["jerry"], "coca_level": 20}],
            "Tom and Jerry went to the store.",
        )
        words = result.get("words", [])
        jerry_entries = [w for w in words if w["lemma"] == "jerry"]
        if jerry_entries:
            # PROPN root → POS not in whitelist → no inheritance
            assert jerry_entries[0]["pos"] != "VERB", \
                f"Jerry should not inherit non-whitelist POS, got {jerry_entries[0]['pos']}"

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
        spaCy mis-tags the capitalized common noun as PROPN.  The word
        appears in lowercase elsewhere in the text ("a boa"), which is
        the signal that it's a common noun, not a proper noun.
        """
        result = _run_pipeline(
            [{"lemma": "boa", "rep": "boa",
              "forms": ["boa", "boas"], "coca_level": 12}],
            "It was a boa.  In the book, Boa constrictors swallow their prey.",
        )
        words = result["words"]
        # Find the Boa entry
        boa_entry = [w for w in words if w["lemma"] == "boa"]
        assert len(boa_entry) == 1, f"expected 1 boa entry, got {len(boa_entry)}"
        assert boa_entry[0]["pos"] == "NOUN", \
            f"expected NOUN, got {boa_entry[0]['pos']}"

    def test_genuine_propn_preserves_lemma_capitalization(self):
        """Mid-sentence genuine proper noun → lemma keeps original casing.

        'Jupiter' is a genuine proper noun (never appears lowercase in text).
        _determine_lemma should return 'Jupiter', not 'jupiter'.
        The PROPN→NOUN revert guard restores pos=PROPN; this test ensures
        lemma also preserves the original capitalisation.
        """
        result = _run_pipeline(
            [{"lemma": "jupiter", "rep": "jupiter",
              "forms": ["jupiter"], "coca_level": 16}],
            "I knew about planets such as Earth, Jupiter, Mars and Venus.",
        )
        words = result["words"]
        j_entry = [w for w in words if w["lemma"] == "Jupiter"]
        assert len(j_entry) == 1, (
            f"expected 1 Jupiter entry, got {len(j_entry)}: "
            f"{[w['lemma'] for w in words]}"
        )
        assert j_entry[0]["pos"] == "PROPN", (
            f"expected PROPN, got {j_entry[0]['pos']}"
        )

    def test_start_offset_negative_uses_full_text(self):
        """--start-offset -1 disables preamble detection and uses full text.
        Without the fix, text[-1:] returns only the last character, so 0
        sentences are found and the word is unmatched."""
        result = _run_pipeline(
            [{"lemma": "magnificent", "rep": "magnificent",
              "forms": ["magnificent"], "coca_level": 4}],
            # Word appears early in the text.  If --start-offset -1 slices
            # to the last char, the word won't be found.
            "I saw a magnificent picture in a book.  It was wonderful.",
            extra_args=["--start-offset", "-1"],
        )
        assert len(result["words"]) == 1, (
            f"expected 1 word, got {len(result['words'])} — "
            f"text[-1:] bug may still be active"
        )
        w = result["words"][0]
        assert "magnificent" in w["sentence"], (
            f"sentence should contain 'magnificent', got: {w['sentence']}"
        )

    def test_char_offset_matches_selected_sentence(self):
        """When a word appears twice in the text, char_offset must point
        to the occurrence in the SELECTED sentence, not the first
        occurrence found by a global scan."""
        text = (
            "He demanded, abruptly: Do you come from another planet? "
            "But he did not reply. "
            "The little prince asked me abruptly, as if seized by a grave "
            "doubt, whether sheep eat bushes."
        )
        result = _run_pipeline(
            [{"lemma": "abruptly", "rep": "abruptly",
              "forms": ["abruptly"], "coca_level": 4}],
            text,
        )
        w = result["words"][0]
        # Verify the sentence contains "abruptly"
        assert "abruptly" in w["sentence"], (
            f"sentence should contain 'abruptly', got: {w['sentence']}"
        )
        # Verify char_offset points into the source text at the correct word
        assert w["char_offset"] >= 0, "char_offset should be non-negative"
        # Verify the character at char_offset is the start of "abruptly"
        word_at_offset = text[w["char_offset"]:w["char_offset"] + 8]
        assert word_at_offset == "abruptly", (
            f"char_offset {w['char_offset']} should point to 'abruptly', "
            f"but found {repr(word_at_offset)}.  "
            f"Selected sentence: {w['sentence']}"
        )

    def test_adv_dobj_becomes_noun(self):
        """ADV + dobj (direct object) → NOUN.  dep=dobj contradicts ADV
        because direct objects must be nominals.  This catches spaCy
        mis-tags like 'sprig' being tagged ADV instead of NOUN."""
        result = _run_pipeline(
            [{"lemma": "sprig", "rep": "sprig",
              "forms": ["sprig"], "coca_level": 8}],
            "Then this little seed will stretch itself and begin, timidly at "
            "first, to push a charming little sprig inoffensively upward "
            "toward the sun.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", f"expected NOUN, got {w['pos']}"

    def test_propn_to_noun_lowercases_lemma(self):
        """Non-PROPN lemma is always lowercased at output.

        'Asteroid' in 'Asteroid 325' may be tagged ADJ by spaCy (noun
        modifier), and 'asteroid' in 'This asteroid...' is NOUN. Both
        are non-PROPN → lemmas must be lowercase. Different POS means
        separate entries (by design — POS prevents cross-POS collision).
        """
        result = _run_pipeline(
            [{"lemma": "asteroid", "rep": "asteroid",
              "forms": ["asteroid"], "coca_level": 8}],
            "This asteroid is small. He named it Asteroid 325.",
        )
        words = result["words"]
        # All entries should have lowercase lemma (not 'Asteroid')
        for w in words:
            assert w["lemma"] == "asteroid", (
                f"expected lowercase lemma 'asteroid', got '{w['lemma']}'"
                f" (pos={w['pos']})"
            )

    def test_genuine_propn_keeps_capital_lemma(self):
        """PROPN entries (Jupiter) keep uppercase lemma after the fix.
        Only non-PROPN lemmas are lowercased; pos=PROPN preserves casing.
        """
        result = _run_pipeline(
            [{"lemma": "jupiter", "rep": "jupiter",
              "forms": ["jupiter"], "coca_level": 16}],
            "I knew about planets such as Earth, Jupiter, Mars and Venus.",
        )
        words = result["words"]
        j_entry = [w for w in words if w["pos"] == "PROPN"]
        assert len(j_entry) >= 1, f"expected at least 1 PROPN, got {j_entry}"
        # PROPN lemmas must keep uppercase
        for w in j_entry:
            assert w["lemma"][0].isupper(), (
                f"PROPN lemma '{w['lemma']}' must start with uppercase"
            )
        # The specific Jupiter entry
        jupiter = [w for w in j_entry if w["lemma"] == "Jupiter"]
        assert len(jupiter) == 1, f"expected Jupiter PROPN, got {[w['lemma'] for w in j_entry]}"


# ── char_offset word-boundary matching ──

class TestCharOffsetWordBoundary:
    """Verify _first_word_boundary_offset uses \b to avoid substring false matches."""

    def test_exact_match(self):
        assert _first_word_boundary_offset("The ram walked.", ["ram"]) == 4

    def test_substring_not_matched(self):
        """'ram' inside 'grammar' must NOT match."""
        assert _first_word_boundary_offset("grammar is hard", ["ram"]) == -1

    def test_punctuation_adjacent(self):
        """Word followed by punctuation still matches."""
        assert _first_word_boundary_offset("the ram.", ["ram"]) == 4
        assert _first_word_boundary_offset("(ram)", ["ram"]) == 1

    def test_case_insensitive(self):
        assert _first_word_boundary_offset("The RAM is fast.", ["ram"]) == 4
        assert _first_word_boundary_offset("The Ram walked.", ["ram"]) == 4

    def test_no_match_returns_neg1(self):
        assert _first_word_boundary_offset("hello world", ["xyzzy"]) == -1

    def test_multiple_forms_first_wins(self):
        """First form that matches wins; forms are tried in order."""
        text = "The rams walked. The ram ate."
        # 'ram' in 'rams' has NO trailing \b (s is a word char), so first
        # match is 'ram' at position 21 (standalone "ram")
        assert _first_word_boundary_offset(text, ["ram", "rams"]) == 21
        # Reversed order: 'rams' matches first at position 4
        assert _first_word_boundary_offset(text, ["rams", "ram"]) == 4

    def test_empty_forms_returns_neg1(self):
        assert _first_word_boundary_offset("hello world", []) == -1

    def test_empty_form_skipped(self):
        """Empty string in forms list is skipped gracefully."""
        assert _first_word_boundary_offset("hello world", ["", "world"]) == 6

    def test_special_regex_chars_in_form(self):
        """re.escape prevents regex errors from special chars in form."""
        # Dot is a regex wildcard; re.escape makes it literal
        assert _first_word_boundary_offset("hello a.b world", ["a.b"]) == 6
        # Asterisk
        assert _first_word_boundary_offset("hello a*b world", ["a*b"]) == 6


# ── _has_sentence_ending (check_step_completed.py) ──


class TestEndOffset:
    """Verify --end-offset limits sentence matching to a character range."""

    def test_end_offset_excludes_sentences_beyond(self):
        """Word only in second sentence which is beyond --end-offset → no match."""
        result = _run_pipeline(
            [{"lemma": "unique", "rep": "unique",
              "forms": ["unique"], "coca_level": 5}],
            "First sentence here. Second sentence with unique word here.",
            extra_args=["--start-offset", "0", "--end-offset", "25"],
        )
        # "Second sentence with unique word here" starts at char 25,
        # but --end-offset 25 means text[:25] = "First sentence here." only.
        # So "unique" has no matching sentence → excluded.
        assert len(result["words"]) == 0

    def test_end_offset_includes_sentence_within_range(self):
        """Word in a sentence fully within [start:end) → matched."""
        result = _run_pipeline(
            [{"lemma": "unique", "rep": "unique",
              "forms": ["unique"], "coca_level": 5}],
            "First sentence here. Unique word here end.",
            extra_args=["--start-offset", "0", "--end-offset", "100"],
        )
        # Both sentences are within range → unique should match
        assert len(result["words"]) >= 1
        assert any(w["lemma"] == "unique" for w in result["words"])

    def test_end_offset_default_full_text(self):
        """Without --end-offset, full text is searched (backward compat)."""
        result = _run_pipeline(
            [{"lemma": "unique", "rep": "unique",
              "forms": ["unique"], "coca_level": 5}],
            "First sentence here. Second sentence with unique word here.",
            extra_args=["--start-offset", "0"],
        )
        # Full text → unique at the end should be matched
        assert len(result["words"]) >= 1
        assert any(w["lemma"] == "unique" for w in result["words"])

    def test_end_offset_with_start_offset(self):
        """Words in [start:end) matched, words beyond end not matched."""
        # "hello" at char 0, "world" at char 27
        result = _run_pipeline(
            [
                {"lemma": "hello", "rep": "hello", "forms": ["hello"], "coca_level": 5},
                {"lemma": "world", "rep": "world", "forms": ["world"], "coca_level": 5},
            ],
            "Hello is here first. World is beyond the cutoff point here.",
            extra_args=["--start-offset", "0", "--end-offset", "24"],
        )
        words = {w["lemma"] for w in result["words"]}
        assert "hello" in words
        # "World" should NOT match (its sentence starts beyond char 24)
        assert "world" not in words


class TestCheckStepCompleted:
    """Test _has_sentence_ending() — fragment detection for Step 2B guard."""

    def test_ends_with_period(self):
        assert _has_sentence_ending("This is complete.") is True

    def test_ends_with_question_mark(self):
        assert _has_sentence_ending("Is it?") is True

    def test_ends_with_exclamation(self):
        assert _has_sentence_ending("Wow!") is True

    def test_no_ending_punctuation(self):
        assert _has_sentence_ending("This has no ending") is False

    def test_quote_no_punctuation(self):
        assert _has_sentence_ending('"scarcely any bigger') is False

    def test_curly_quotes_stripped(self):
        assert _has_sentence_ending(
            '“Once upon a time there was a prince.”'
        ) is True
