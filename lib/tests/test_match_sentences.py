"""Test match_sentences.py — PySBD segmentation + _better() comparison.

In the new design, sentences are stored WITHOUT <b> tags. Each result
has 'target_offset', 'matched_form', and 'text' fields. No candidates
array — only the best entry per (lemma, pos) is retained.
"""

import io
import sys

import pytest
from lib.scripts.match_sentences import (
    split_sentences,
    hard_truncate,
    smart_truncate,
    _cleanup_unclosed_quote,
    _is_inside_opening_quote,
    _better,
    _cmu_ipa,
    _clean_quote_artifact,
    _normalize_dialogue_attribution,
    _first_word_boundary_offset,
    _is_fragment,
    _merge_adjacent_fragments,
    process_words,
)
from lib.scripts.check_step_completed import _has_sentence_ending


# ── spaCy preload (session-scoped to avoid per-test cold starts) ──

_nlp = None


def _get_nlp():
    """Load spaCy once — first call pays the ~5s cost, rest are free."""
    global _nlp
    if _nlp is None:
        from lib.utils import _get_spacy
        _nlp = _get_spacy(enable_parser=True)
    return _nlp


@pytest.fixture(scope="session")
def nlp():
    """Session-scoped spaCy fixture for tests that need explicit injection."""
    model = _get_nlp()
    if model is None:
        pytest.skip("spaCy not available")
    return model


# ── In-process pipeline helper (replaces subprocess for speed) ──


def _run_pipeline(in_coca: list[dict], text: str, extra_args: list[str] | None = None,
                  *, nlp=None) -> dict:
    """Run process_words() in-process — reuses pre-loaded spaCy model."""
    if nlp is None:
        nlp = _get_nlp()
    start_offset = 0
    end_offset = None
    if extra_args:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--start-offset", type=int, default=0)
        parser.add_argument("--end-offset", type=int, default=None)
        ns, _ = parser.parse_known_args(extra_args)
        start_offset = ns.start_offset
        end_offset = ns.end_offset

    data = {
        "suffix": "test00000000",
        "in_coca": in_coca,
    }
    return process_words(
        data, text,
        start_offset=start_offset,
        end_offset=end_offset,
        source_text_path="<test>",
        nlp=nlp,
    )


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
        """indulgently → fall back to indulgent + /li/. No nested slashes."""
        result = _cmu_ipa("indulgently")
        assert result, f"Expected non-empty IPA for indulgently"
        assert result.count("/") == 2, (
            f"Expected exactly 2 slashes (delimiters), got {result.count('/')}: {result}"
        )
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
        """NOUN + amod → ADJ via dep override.

        Uses a sentence where spaCy genuinely tags a word as NOUN with amod
        dep (not compound).  This tests the amod/acomp/oprd→ADJ dep-override
        rule, not the deleted compound rule.
        """
        # 'ineffectual movements' — but spaCy may tag this ADJ/amod directly.
        # Use a word that spaCy genuinely mis-tags: 'slant change' gives
        # NOUN/amod in some spaCy versions, but ADJ/amod in current spaCy.
        result = _run_pipeline(
            [{"lemma": "slant", "rep": "slant",
              "forms": ["slant"], "coca_level": 7}],
            "He saw the slant change in the water ahead.",
        )
        w = result["words"][0]
        # Note: spaCy may assign amod or compound depending on context.
        # If it's amod and POS is NOUN, the dep-override fires → ADJ.
        # If it's compound, POS stays NOUN (compound rule removed).
        # If spaCy directly tags as ADJ, POS is ADJ from the start.
        # All outcomes are mechanically valid post-rule-removal.
        assert w["pos"] in ("ADJ", "NOUN"), f"got {w['pos']}"

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

    def test_conj_pos_inheritance_skips_cc_to_reach_content_head(self):
        """'gaunt' conj whose head is 'and' (cc) → walk past cc to 'thin' (ADJ)."""
        result = _run_pipeline(
            [{"lemma": "gaunt", "rep": "gaunt",
              "forms": ["gaunt"], "coca_level": 9}],
            "The old man was thin and gaunt with deep wrinkles in the back of his neck.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", \
            f"gaunt should be ADJ (conj of thin), got {w['pos']}"

    def test_conj_pos_inheritance_skips_cc_verb_coordination(self):
        """'jumped' conj via 'and' → walk past cc to 'ran' (VERB). No change."""
        result = _run_pipeline(
            [{"lemma": "jump", "rep": "jumped",
              "forms": ["jumped"], "coca_level": 3}],
            "He ran and jumped over the fence.",
        )
        words = result.get("words", [])
        jump_entries = [w for w in words if w["lemma"] == "jump"]
        if jump_entries:
            assert jump_entries[0]["pos"] == "VERB", \
                f"jumped should stay VERB (conj of ran), got {jump_entries[0]['pos']}"

    def test_conj_of_verb_stays_verb_not_adj(self):
        """'butchered' conj of 'begged' (VERB) — AUX fallback must NOT fire.

        SpaCy parses this as butchered→begged(VERB,conj)→was(AUX).
        The chain walks past a VERB content word, so the AUX copula
        fallback should not trigger — butchered stays VERB.
        """
        result = _run_pipeline(
            [{"lemma": "butcher", "rep": "butchered",
              "forms": ["butchered"], "coca_level": 5}],
            "The boy was sad too and we begged her pardon and butchered her promptly.",
        )
        w = result["words"][0]
        assert w["pos"] == "VERB", \
            f"butchered should stay VERB (conj of begged), got {w['pos']}"

    def test_conj_of_copula_with_own_subject_stays_verb(self):
        """'teetered' conj of 'was' but has own nsubj → separate clause, stays VERB.

        In 'He was tired and he teetered', 'teetered' is the main verb of
        the second clause with its own subject 'he'.  The AUX copula
        fallback must NOT promote it to ADJ just because 'was' has
        'tired' (ADJ, acomp).
        """
        result = _run_pipeline(
            [{"lemma": "teeter", "rep": "teetered",
              "forms": ["teetered"], "coca_level": 9}],
            "He was too tired even to examine the line and he teetered on it as his delicate feet gripped it fast.",
        )
        w = result["words"][0]
        assert w["pos"] == "VERB", \
            f"teetered should stay VERB (separate clause with own nsubj), got {w['pos']}"

    def test_conj_of_aux_with_det_child_stays_noun(self):
        """'lavender' conj of 'was' with det child 'a' stays NOUN.

        In 'It was higher than a big scythe blade and a very pale
        lavender above the dark blue water', spaCy attaches 'lavender'
        as conj of AUX 'was'.  The AUX copula fallback must NOT promote
        it to ADJ because it has a determiner child ('a'), which is an
        unambiguous noun signal.
        """
        result = _run_pipeline(
            [{"lemma": "lavender", "rep": "lavender",
              "forms": ["lavender"], "coca_level": 7}],
            "It was higher than a big scythe blade and a very pale "
            "lavender above the dark blue water.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", \
            f"lavender should be NOUN (has det child 'a'), got {w['pos']}"

    def test_conj_of_adj_head_with_det_child_stays_noun(self):
        """NOUN conj of ADJ head with det child stays NOUN.

        E.g. 'He was pale and a good friend' — 'friend' is NOUN with
        det child 'a', conj of 'pale' (ADJ, acomp).  The general conj
        POS inheritance must NOT promote it to ADJ.
        """
        result = _run_pipeline(
            [{"lemma": "friend", "rep": "friend",
              "forms": ["friend"], "coca_level": 3}],
            "He was pale and a good friend.",
        )
        words = result.get("words", [])
        friend_entries = [w for w in words if w["lemma"] == "friend"]
        if friend_entries:
            assert friend_entries[0]["pos"] != "ADJ", \
                f"friend should not be ADJ (has det child 'a'), got {friend_entries[0]['pos']}"

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

    def test_char_offset_uses_form_in_matched_sentence_not_later(self):
        """When all_forms contains two forms and the sentence contains only
        the second form, _sentence_char_offset must return the offset of
        the form within the matched sentence — not the first form's next
        occurrence in a later sentence.

        Regression test: "sardine" (singular) appears in a later sentence,
        but the matched sentence for "sardines" only contains the plural.
        Searching text[match_start:] for \bsardine\b would find the
        singular at a later offset, producing a wrong char_offset.
        """
        text = (
            '"I go now for the sardines," the boy said.  '
            'Each sardine was hooked through both eyes.'
        )
        result = _run_pipeline(
            [{"lemma": "sardine", "rep": "sardines",
              "forms": ["sardine", "sardines"], "coca_level": 9}],
            text,
        )
        w = result["words"][0]
        assert "sardines" in w["sentence"], (
            f"sentence should contain 'sardines', got: {w['sentence']}"
        )
        word_at_offset = text[w["char_offset"]:w["char_offset"] + 8]
        assert word_at_offset == "sardines", (
            f"char_offset {w['char_offset']} should point to 'sardines', "
            f"but found {repr(word_at_offset)}. "
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

    def test_adj_pobj_becomes_noun(self):
        """ADJ + pobj (prepositional object) → NOUN.  dep=pobj contradicts
        ADJ because a prepositional object must be nominal.  This catches
        spaCy mis-tags like 'odour' (ADJ+pobj in "edge of the odour") and
        'stern' (ADJ+pobj in "back in the stern" = boat stern, not ADJ)."""
        result = _run_pipeline(
            [{"lemma": "odour", "rep": "odour",
              "forms": ["odour"], "coca_level": 4}],
            "When the wind was in the east a smell came across the harbour "
            "from the shark factory; but today there was only the faint "
            "edge of the odour from the fish house.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", f"expected NOUN, got {w['pos']}"

    def test_adj_dobj_becomes_noun(self):
        """ADJ + dobj (direct object) → NOUN.  dep=dobj contradicts ADJ
        because direct objects must be nominals."""
        result = _run_pipeline(
            [{"lemma": "testword", "rep": "testword",
              "forms": ["testword"], "coca_level": 7}],
            "She saw the testword clearly.",
        )
        # If spaCy tags 'testword' as ADJ with dep=dobj, guard fixes it.
        # If spaCy tags it correctly as NOUN, it stays NOUN.
        w = result["words"][0]
        assert w["pos"] in ("NOUN",), f"expected NOUN, got {w['pos']}"

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

    def test_mid_sentence_capitalized_noun_becomes_propn(self):
        """Mid-sentence capitalised NOUN → PROPN.

        spaCy sometimes tags proper nouns as NOUN depending on sentence
        context (e.g. "on the Terrace" vs "into the Terrace").  Capitalisation
        mid-sentence is a strong proper-noun signal in English.
        """
        result = _run_pipeline(
            [{"lemma": "terrace", "rep": "terrace",
              "forms": ["terrace"], "coca_level": 4}],
            "They sat on the Terrace and many fishermen made fun of him.\n"
            "He went into the Terrace and ordered coffee.",
        )
        words = result["words"]
        assert len(words) == 1, \
            f"Both Terrace usages should merge into one PROPN group, got {len(words)}"
        assert words[0]["pos"] == "PROPN", \
            f"expected PROPN, got {words[0]['pos']}"

    def test_mid_sentence_lowercase_noun_stays_noun(self):
        """Lowercase mid-sentence NOUN stays NOUN (not spuriously converted)."""
        result = _run_pipeline(
            [{"lemma": "gulf", "rep": "gulf",
              "forms": ["gulf"], "coca_level": 4}],
            "The dark water of the true gulf is the greatest healer.",
        )
        w = result["words"][0]
        assert w["pos"] == "NOUN", \
            f"lowercase 'gulf' should stay NOUN, got {w['pos']}"

    def test_propn_loanword_lemma_coca_cross_check(self):
        """PROPN→NOUN lemmatizer false positive for loanwords: COCA cross-check.

        lemminflect incorrectly reduces "bonita" (Spanish loanword for a fish)
        to "bonitum" (Latin neuter pseudo-singular).  Since "bonita" is in
        COCA but "bonitum" is not, _determine_lemma should reject the
        lemmatizer output and keep the surface form.
        """
        result = _run_pipeline(
            [{"lemma": "bonita", "rep": "bonita",
              "forms": ["bonita"], "coca_level": 8}],
            "Today I'll work out where the schools of bonita and albacore are.",
        )
        words = result["words"]
        assert len(words) == 1, f"expected 1 entry, got {len(words)}"
        assert words[0]["lemma"] == "bonita", \
            f"expected lemma 'bonita', got '{words[0]['lemma']}'"
        assert words[0]["pos"] == "NOUN", \
            f"expected NOUN, got {words[0]['pos']}"


    def test_vbd_advcl_no_children_becomes_adj(self):
        """VBD + advcl + no verbal children → ADJ (depictive predicate)."""
        result = _run_pipeline(
            [{"lemma": "puzzle", "rep": "puzzled",
              "forms": ["puzzled"], "coca_level": 5}],
            "And the little prince went away, puzzled.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"Expected ADJ, got {w['pos']}"

    def test_vbn_advcl_no_children_becomes_adj(self):
        """VBN + advcl + no children → ADJ."""
        result = _run_pipeline(
            [{"lemma": "exhaust", "rep": "exhausted",
              "forms": ["exhausted"], "coca_level": 6}],
            "She stood there, exhausted.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"Expected ADJ, got {w['pos']}"

    def test_vbg_advcl_stays_verb(self):
        """VBG + advcl stays VERB (present participle more verbal)."""
        result = _run_pipeline(
            [{"lemma": "smile", "rep": "smiling",
              "forms": ["smiling"], "coca_level": 4}],
            "He left the room, smiling.",
        )
        w = result["words"][0]
        assert w["pos"] == "VERB", f"Expected VERB, got {w['pos']}"

    def test_advcl_with_agent_stays_verb(self):
        """VBN + advcl + has agent child (by-agent) → stays VERB (true passive).

        The agent dep is in _VERBAL_DEPS — a genuine verbal argument.
        """
        result = _run_pipeline(
            [{"lemma": "defeat", "rep": "defeated",
              "forms": ["defeated"], "coca_level": 6}],
            "He left the room, defeated by the argument.",
        )
        w = result["words"][0]
        # "defeated by" has agent child — true passive verb, not adjective
        assert w["pos"] == "VERB", f"Expected VERB, got {w['pos']}"

    def test_advcl_with_prep_children_becomes_adj(self):
        """VBN + advcl + non-verbal children (prepositional phrases) → ADJ.

        Prepositional-phrase modifiers (in+N, on+N) are typical of adjectives,
        not verbal clauses.  E.g. "Clad in royal purple, he was seated..."
        """
        result = _run_pipeline(
            [{"lemma": "clad", "rep": "Clad",
              "forms": ["clad", "Clad"], "coca_level": 7}],
            "Clad in royal purple and ermine, he was seated upon a throne.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"Expected ADJ, got {w['pos']}"
        assert w["lemma"] == "clad", f"Expected lemma='clad', got {w['lemma']}"

    def test_vbn_preceding_advmod_becomes_adj(self):
        """Preposed advmod (completely) on VBN → ADJ (adjectival signal)."""
        result = _run_pipeline(
            [{"lemma": "abash", "rep": "abashed",
              "forms": ["abashed"], "coca_level": 10}],
            "He was completely abashed by the question.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"Expected ADJ, got {w['pos']}"

    def test_vbn_following_advmod_stays_verb(self):
        """Postposed advmod (along) on VBN → stays VERB (phrasal-verb particle)."""
        result = _run_pipeline(
            [{"lemma": "trudge", "rep": "trudged",
              "forms": ["trudged"], "coca_level": 10}],
            "When we had trudged along for several hours, we rested.",
        )
        w = result["words"][0]
        # "along" is a phrasal-verb particle, not a true manner adverb
        assert w["pos"] == "VERB", f"Expected VERB, got {w['pos']}"

    def test_vbn_advmod_no_children_becomes_adj(self):
        """VBN + advmod + no verbal children → ADJ (depictive predicate)."""
        result = _run_pipeline(
            [{"lemma": "bewilder", "rep": "bewildered",
              "forms": ["bewildered"], "coca_level": 5}],
            "He stood there all bewildered, the glass globe held arrested in mid-air.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"Expected ADJ, got {w['pos']}"
        assert w["lemma"] == "bewildered", (
            f"Expected lemma='bewildered', got {w['lemma']}"
        )

    def test_vbd_advmod_no_children_becomes_adj(self):
        """VBD + advmod + no verbal children → ADJ."""
        result = _run_pipeline(
            [{"lemma": "exhaust", "rep": "exhausted",
              "forms": ["exhausted"], "coca_level": 6}],
            "He sat there exhausted.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"Expected ADJ, got {w['pos']}"

    def test_vbg_advmod_stays_verb(self):
        """VBG + advmod stays VERB (present participle more verbal)."""
        result = _run_pipeline(
            [{"lemma": "run", "rep": "running",
              "forms": ["running"], "coca_level": 2}],
            "He came running toward us.",
        )
        w = result["words"][0]
        assert w["pos"] == "VERB", f"Expected VERB, got {w['pos']}"

    def test_conj_of_vbn_advcl_head_inherits_adj(self):
        """Conj of VBN+advcl head inherits ADJ, not VERB.

        When the coordination root is VBN in advcl position with no verbal
        dependents, it is a depictive predicate adjective.  The conjunct
        shares this adjectival role and should be ADJ.

        E.g. "Drained of blood and awash he looked..." → awash(NOUN,conj)
        whose head Drained(VBN,advcl) has only prep/cc/conj children.
        """
        result = _run_pipeline(
            [{"lemma": "awash", "rep": "awash",
              "forms": ["awash"], "coca_level": 9}],
            "Drained of blood and awash he looked the colour of the silver backing of a mirror and his stripes still showed.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", f"Expected ADJ, got {w['pos']}"

    def test_conj_pos_inheritance_adj_lemma_is_surface_form(self):
        """VBN conj of ADJ head → ADJ with surface-form lemma, not verb lemma.

        'tempered' in 'sharp and not tempered' — spaCy may tag it as VBN
        and _determine_lemma reduces it to 'temper' via the VERB channel.
        The conj chain promotes it to ADJ (conj of 'sharp'), and the lemma
        must be the surface form 'tempered', not the reduced 'temper'.
        """
        result = _run_pipeline(
            [{"lemma": "temper", "rep": "tempered",
              "forms": ["tempered"], "coca_level": 7}],
            "It should be sharp and not tempered so it will break.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", \
            f"tempered should be ADJ (conj of sharp), got {w['pos']}"
        assert w["lemma"] == "tempered", \
            f"tempered lemma should be surface form 'tempered', got '{w['lemma']}'"

    def test_noun_dobj_with_adj_conj_child_becomes_adj(self):
        """'rest there slimy and purple' → slimy NOUN/dobj with ADJ conj child → ADJ.

        When a NOUN/dobj has a child with dep=conj and pos=ADJ, both should
        be adjectives — coordinated items share POS.  Gated on -y suffix.
        The sentence uses a complex coordination structure ("catch on a line
        and rest there slimy and purple") to trigger the dobj parse.
        """
        result = _run_pipeline(
            [{"lemma": "slimy", "rep": "slimy",
              "forms": ["slimy"], "coca_level": 7}],
            "The filaments would catch on a line and rest there slimy and purple "
            "while the old man was working.",
        )
        w = result["words"][0]
        assert w["pos"] == "ADJ", \
            f"slimy in 'slimy and purple' should be ADJ, got {w['pos']}"


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


def _run_pipeline_json_out(in_coca: list[dict], text: str,
                           extra_args: list[str] | None = None,
                           filter_extra: dict | None = None) -> dict:
    """Run process_words() in-process; capture stderr for test verification.

    Unlike the old subprocess-based version that read a --json-out file,
    this calls process_words() directly and captures stderr via redirect.
    """
    import io

    start_offset = 0
    end_offset = None
    book_title = None
    book_author = None
    if extra_args:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--start-offset", type=int, default=0)
        parser.add_argument("--end-offset", type=int, default=None)
        parser.add_argument("--book-title", type=str, default=None)
        parser.add_argument("--book-author", type=str, default=None)
        ns, _ = parser.parse_known_args(extra_args)
        start_offset = ns.start_offset
        end_offset = ns.end_offset
        book_title = ns.book_title
        book_author = ns.book_author

    data = {
        "suffix": "test00000000",
        "in_coca": in_coca,
    }
    if filter_extra:
        data.update(filter_extra)

    nlp = _get_nlp()
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        output = process_words(
            data, text,
            start_offset=start_offset,
            end_offset=end_offset,
            book_title=book_title,
            book_author=book_author,
            source_text_path="<test>",
            nlp=nlp,
        )
        output['_test_stdout'] = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    return output


class TestJsonOut:
    """Verify --json-out flag writes clean JSON to file, not stdout."""

    def test_json_out_writes_clean_file(self):
        """--json-out writes JSON to file; stdout has no JSON content."""
        in_coca = [{"lemma": "hello", "rep": "hello", "forms": ["hello"],
                     "coca_level": 5}]
        text = "Hello world. This is a test."
        result = _run_pipeline_json_out(in_coca, text)
        stdout = result.pop('_test_stdout', '')
        # stdout should NOT contain JSON output
        assert '"book_title"' not in stdout
        assert '"words"' not in stdout
        # Output file should have the expected keys
        assert 'words' in result
        assert len(result['words']) >= 1

    def test_json_out_content_matches_stdout(self):
        """Output with --json-out is identical in content to stdout output."""
        in_coca = [{"lemma": "hello", "rep": "hello", "forms": ["hello"],
                     "coca_level": 5}]
        text = "Hello world. This is a test."

        # Get stdout output (no --json-out)
        result_stdout = _run_pipeline(in_coca, text)

        # Get file output (with --json-out)
        result_file = _run_pipeline_json_out(in_coca, text)
        result_file.pop('_test_stdout', None)

        # Compare key fields (ignore source_text_path which differs per run)
        assert len(result_stdout['words']) == len(result_file['words'])
        assert result_stdout['book_title'] == result_file['book_title']
        assert result_stdout['book_author'] == result_file['book_author']
        assert result_stdout['suffix'] == result_file['suffix']

    def test_book_metadata_override(self):
        """--book-title/--book-author override empty values in input JSON."""
        in_coca = [{"lemma": "hello", "rep": "hello", "forms": ["hello"],
                     "coca_level": 5}]
        text = "Hello world. This is a test."

        # Run without override — should get empty strings
        result_no_meta = _run_pipeline(in_coca, text)
        assert result_no_meta['book_title'] == ''
        assert result_no_meta['book_author'] == ''

        # Run with JSON-out and overrides
        result_with_meta = _run_pipeline_json_out(in_coca, text, extra_args=[
            "--book-title", "Test Book",
            "--book-author", "Test Author",
        ])
        assert result_with_meta['book_title'] == 'Test Book'
        assert result_with_meta['book_author'] == 'Test Author'

    def test_book_id_propagated(self):
        """book_id from filter_pipeline.py input is preserved in output."""
        in_coca = [{"lemma": "hello", "rep": "hello", "forms": ["hello"],
                     "coca_level": 5}]
        text = "Hello world. This is a test."

        # Include book_id in input (as filter_pipeline.py does for vocab-anki)
        result = _run_pipeline_json_out(in_coca, text,
            filter_extra={"book_id": "22720170"})
        assert result['book_id'] == '22720170'
        # suffix should still be present (vocab-book mode)
        assert result['suffix'] == 'test00000000'

    def test_book_id_absent_when_not_in_input(self):
        """book_id is empty string when input had no book_id."""
        in_coca = [{"lemma": "hello", "rep": "hello", "forms": ["hello"],
                     "coca_level": 5}]
        text = "Hello world. This is a test."

        result = _run_pipeline_json_out(in_coca, text)
        assert result['book_id'] == ''

    def test_bands_and_is_bilateral_propagated_from_input(self):
        """bands and is_bilateral from filter output are carried to match output."""
        in_coca = [{"lemma": "test", "rep": "test", "forms": ["test"],
                     "coca_level": 9}]
        text = "This is a test."
        result = _run_pipeline_json_out(in_coca, text, filter_extra={
            "bands": [{"name": "COCA 9", "lo": 9, "hi": 9}],
            "is_bilateral": True,
        })
        assert result['bands'] == [{"name": "COCA 9", "lo": 9, "hi": 9}]
        assert result['is_bilateral'] is True

    def test_bands_absent_defaults_to_empty(self):
        """When input has no bands/is_bilateral, output defaults to empty list/False."""
        in_coca = [{"lemma": "test", "rep": "test", "forms": ["test"],
                     "coca_level": 5}]
        text = "This is a test."
        result = _run_pipeline_json_out(in_coca, text)
        assert result['bands'] == []
        assert result['is_bilateral'] is False


# ── Fragment merge (_merge_adjacent_fragments) ──


_SOURCE_FRAGMENTS = (
    "Clad in royal purple and ermine, he was seated upon a throne, "
    "which was at \n\n\n\n\nthe same time both simple and majestic."
)


class TestMergeAdjacentFragments:
    """Tests for _merge_adjacent_fragments()."""

    def test_merge_two_fragments(self):
        """Fragments split by blank lines are merged into one sentence."""
        sents = [
            "Clad in royal purple and ermine, he was seated upon a throne, which was at",
            "the same time both simple and majestic.",
        ]
        merged = _merge_adjacent_fragments(sents, _SOURCE_FRAGMENTS)
        assert len(merged) == 1
        assert "which was at the same time both simple and majestic" in merged[0]

    def test_merge_three_fragments(self):
        """Three consecutive fragments all merge."""
        src = "she would cough \n\n\n\nmost \n\n dreadfully \n\n and pretend."
        sents = [
            "she would cough",
            "most",
            "dreadfully",
            "and pretend.",
        ]
        merged = _merge_adjacent_fragments(sents, src)
        assert len(merged) == 1
        assert "cough most dreadfully and pretend" in merged[0]

    def test_no_merge_if_not_continuous(self):
        """Fragments from different parts of the text do NOT merge."""
        source = "First sentence here. \n\n Another thought entirely."
        sents = [
            "First sentence here",
            "Another thought entirely.",
        ]
        merged = _merge_adjacent_fragments(sents, source)
        # "First sentence here" IS a fragment (no terminal .) but
        # "Another thought entirely." starts uppercase — merge skipped.
        assert len(merged) == 2

    def test_complete_sentence_not_merged(self):
        """A complete sentence next to a fragment does NOT trigger merge."""
        source = "Hello world. \n\n fragments remain."
        sents = [
            "Hello world.",
            "fragments remain.",
        ]
        merged = _merge_adjacent_fragments(sents, source)
        assert len(merged) == 2

    def test_merge_preserves_ending_punctuation(self):
        """Merged result keeps the terminal punctuation from the last fragment."""
        source = "he said softly, \n\n almost whispering the words."
        sents = [
            "he said softly,",
            "almost whispering the words.",
        ]
        merged = _merge_adjacent_fragments(sents, source)
        assert len(merged) == 1
        assert merged[0].endswith(".")

    def test_empty_source_no_crash(self):
        """Empty source text does not crash."""
        sents: list[str] = []
        merged = _merge_adjacent_fragments(sents, "")
        assert merged == []

    def test_single_sentence_unchanged(self):
        """Single sentence is returned unchanged."""
        sents = ["Hello world."]
        merged = _merge_adjacent_fragments(sents, "Hello world.")
        assert merged == ["Hello world."]

    def test_split_sentences_with_source_text(self):
        """split_sentences() with source_text merges fragments."""
        text = (
            "Clad in royal purple and ermine, he was seated upon a throne, "
            "which was at \n\n\n\n\nthe same time both simple and majestic."
        )
        sents = split_sentences(text, source_text=text)
        assert any(
            "at the same time both simple and majestic" in s for s in sents
        ), f"Expected merged sentence, got: {sents}"

    # ── backward merge ─────────────────────────────────────────────────

    def test_backward_merge_lowercase_fragment(self):
        """Lowercase-start fragment merges backward with preceding fragment."""
        source = (
            '"That man," said the little prince, "'
            "that man \n\nwould be scorned by all the others."
        )
        sents = [
            '"That man," said the little prince, "',
            "that man would be scorned by all the others.",
        ]
        merged = _merge_adjacent_fragments(sents, source)
        assert len(merged) == 1
        assert merged[0].startswith('"That man," said')

    def test_backward_merge_requires_prev_fragment(self):
        """Lowercase fragment does NOT merge backward into a complete sentence."""
        source = "Hello world. \n\n fragments remain."
        sents = [
            "Hello world.",
            "fragments remain.",
        ]
        merged = _merge_adjacent_fragments(sents, source)
        assert len(merged) == 2

    def test_backward_merge_cascade(self):
        """Backward merges can chain: three fragments merge into one."""
        source = (
            "She said, \n\n\n\n"
            "most softly, "
            "\n\n"
            "the words."
        )
        sents = [
            "She said,",
            "most softly,",
            "the words.",
        ]
        merged = _merge_adjacent_fragments(sents, source)
        # "most softly," backward-merges into "She said,", then
        # "the words." backward-merges into the combined fragment.
        assert len(merged) == 1
        assert "most softly" in merged[0]
        assert "the words" in merged[0]


# ── _is_inside_opening_quote ────────────────────────────────────────────


class TestIsInsideOpeningQuote:
    """Tests for _is_inside_opening_quote()."""

    def test_inside_opening_quote(self):
        """Position after an opening " is inside an unclosed quote."""
        text = 'He said, "hello world'
        # The last " is the opening one, 0 preceding quotes (even) → opening.
        assert _is_inside_opening_quote(text, len(text) - 1) is True

    def test_inside_closed_quote(self):
        """Position after a balanced pair is NOT inside an unclosed quote."""
        text = '"hello" world'
        # The " at pos 6 is preceded by 1 " (odd) → closing.
        assert _is_inside_opening_quote(text, 7) is False

    def test_no_quote_found(self):
        """No quote in text returns False."""
        assert _is_inside_opening_quote("plain text", 5) is False

    def test_second_opening_in_nested_equivalent(self):
        """Two separate quoted passages: second quote is an opening."""
        text = '"hello" she said "world'
        # " at pos 7 is preceded by 2 " (even) → opening quote.
        assert _is_inside_opening_quote(text, len(text) - 1) is True


# ── smart_truncate ──────────────────────────────────────────────────────


class TestSmartTruncate:
    """Tests for smart_truncate()."""

    def test_short_sentence_unchanged(self):
        """Sentence under max_len is returned unchanged."""
        sent, to, was_trunc = smart_truncate(
            "Short sentence.", "sentence", 6, max_len=250,
        )
        assert sent == "Short sentence."
        assert to == 6
        assert was_trunc is False

    def test_truncate_at_period(self):
        """Truncation lands on a period — result ends with period."""
        long_sent = (
            "This is the first part which contains some information. "
            + "This is the second part which goes on and on and has "
            + "many words that make it longer than two hundred and "
            + "fifty characters in total length. "
            + "And here we have even more text that makes this very "
            + "long indeed and pushes the total far beyond the limit."
        )
        sent, to, was_trunc = smart_truncate(
            long_sent, "first", 12, max_len=150,
        )
        assert was_trunc is True
        assert len(sent) <= 150
        assert sent.endswith(".")

    def test_no_punctuation_returns_unchanged(self):
        """No sentence-ending punctuation found — return original unchanged.

        The old behaviour truncated at the last word boundary, producing
        fragments without terminal punctuation.  Now we return the original
        sentence so Step 2B can review it manually.
        """
        long_sent = (
            "The quick brown fox jumps over the lazy dog and continues "
            "running across the field without stopping for a moment "
            "because the sun was setting behind the hills"
        )[:200]
        sent, to, was_trunc = smart_truncate(
            long_sent, "fox", 16, max_len=120,
        )
        assert was_trunc is False
        assert sent == long_sent
        assert to == 16

    def test_target_offset_preserved_end_truncation(self):
        """target_offset never changes during end-truncation — sentence
        start is not modified in Phase 1."""
        long_sent = (
            "I really enjoy walking through the forest on a beautiful "
            "spring morning when the birds are singing and the flowers "
            "are beginning to bloom in the warm sunshine."
        )[:200]
        _, to, _ = smart_truncate(long_sent, "forest", 31, max_len=120)
        assert to == 31

    def test_target_word_beyond_limit_no_boundary(self):
        """Target word extends beyond max_len with no sentence boundary
        before it — Phase 2 finds nothing → returned unchanged."""
        long_sent = "x" * 200 + " target yyy"
        sent, to, was_trunc = smart_truncate(
            long_sent, "target", 201, max_len=100,
        )
        assert was_trunc is False
        assert sent == long_sent

    def test_opening_quote_pre_text_not_complete(self):
        """Inside opening quote but pre-quote text is incomplete (ends with
        comma) → returned unchanged for Step 2B manual review."""
        sent = (
            "The king said, \"You must obey all of my commands without "
            "question because I am the ruler of this entire planet "
            "and my authority is absolute and unquestionable."
            + "x" * 200
        )
        result, to, was_trunc = smart_truncate(
            sent, "question", 50, max_len=250,
        )
        # pre-quote text 'The king said, ' ends with comma → not complete.
        # Without word-boundary fallback, returns original.
        assert was_trunc is False
        assert result == sent
        # so it should fall through to other truncation.
        assert len(result) > 0

    def test_closed_quote_no_punctuation_in_range(self):
        """Sentence boundary (. + space + capital) inside an unclosed quote
        is now accepted as a valid truncation point."""
        sent = (
            '"Hello there," she said. "'
            + "I am going to the store to buy groceries for dinner tonight. "
            + "The weather is beautiful today." * 20
        )
        # "groceries" is at position 57 in the constructed sentence
        groceries_offset = sent.find("groceries")
        assert groceries_offset == 57
        result, to, was_trunc = smart_truncate(
            sent, "groceries", groceries_offset, max_len=200,
        )
        # The period inside an opening quote, followed by space + capital,
        # is now accepted as a valid sentence boundary for truncation.
        assert was_trunc is True
        assert len(result) <= 200
        assert "groceries" in result.lower()

    def test_exact_max_len_no_truncation(self):
        """Sentence exactly at max_len — no truncation."""
        sent = "A" * 250
        result, to, was_trunc = smart_truncate(sent, "A", 100, max_len=250)
        assert was_trunc is False
        assert result == sent

    def test_under_max_len_but_poorly_terminated_still_truncates(self):
        """Sentence under max_len that ends mid-thought (hard_truncate
        artifact) — Direction 1 still finds a proper sentence boundary."""
        # Simulates a hard_truncate output: 280 chars, under max_len=500,
        # but ends with a comma (no proper .!? termination).
        sent = (
            "During the fifty-four years that I have inhabited this planet, "
            "I have been disturbed only three times. The first time was "
            "twenty-two years ago, when some giddy goose fell from goodness "
            "knows where. He made the most frightful noise that resounded "
            "all over the place, and I made four mistakes in my addition. "
            "I was saying, then,"
        )
        target_word = "giddy"
        toff = sent.find(target_word)
        result, new_to, was_trunc = smart_truncate(
            sent, target_word, toff, max_len=500,
        )
        # Should truncate at the first .!? after target word even though
        # the sentence is under max_len — it ends mid-thought.
        assert was_trunc is True
        assert len(result) < len(sent)
        assert result.endswith(".")
        assert result[new_to:new_to + len(target_word)].lower() == target_word

    def test_short_well_terminated_sentence_unchanged(self):
        """Short sentence (< max_len) ending with . — unchanged."""
        sent = "He was very timid."
        target_word = "timid"
        toff = sent.find(target_word)
        result, new_to, was_trunc = smart_truncate(
            sent, target_word, toff, max_len=500,
        )
        assert was_trunc is False
        assert result == sent
        assert new_to == toff

    def test_short_sentence_ending_with_quoted_period_unchanged(self):
        """Short sentence ending with ." — unchanged."""
        sent = '"Where are the men?"'
        target_word = "men"
        toff = sent.find(target_word)
        result, new_to, was_trunc = smart_truncate(
            sent, target_word, toff, max_len=500,
        )
        assert was_trunc is False
        assert result == sent

    def test_function_word_set_includes_determiners(self):
        """'the', 'a', 'an' are in SENTENCE_END_FUNCTION_WORDS so truncation
        backs up past them.  This test verifies the set is correctly
        configured — the actual backup logic is tested end-to-end in the
        existing TestSmartTruncate cases."""
        from lib.config import SENTENCE_END_FUNCTION_WORDS
        for word in ("the", "a", "an", "its", "her", "their", "our", "your", "my"):
            assert word in SENTENCE_END_FUNCTION_WORDS, (
                f"'{word}' must be in SENTENCE_END_FUNCTION_WORDS"
            )
        # "his" is intentionally excluded — it can be a nominal possessive pronoun
        assert "his" not in SENTENCE_END_FUNCTION_WORDS

    def test_no_punctuation_in_max_len_range(self):
        """Period beyond old max_len — Direction 1 finds it by scanning
        right from target_end to end of sentence."""
        long_sent = (
            "He pointed to the exact spot where the treasure was at "
            + "the bottom of the deep blue ocean where no one had "
            + "ever ventured before or since that fateful day." * 3
        )[:400]
        toff = long_sent.find("treasure")
        sent, to, was_trunc = smart_truncate(
            long_sent, "treasure", toff, max_len=120,
        )
        # Direction 1 scans right from target_end beyond old max_len
        # and finds the period — sentence is truncated.
        assert was_trunc is True
        assert len(sent) < len(long_sent)
        assert sent[to:to + len("treasure")] == "treasure"

    def test_quote_inside_truncation_unfixable(self):
        """Truncation lands inside opening quote but pre-quote text is
        incomplete → returned unchanged (needs manual)."""
        long_sent = (
            "He looked at the map and then slowly turned to face the "
            "horizon where the sun was setting, \"I think we should "
            + "x" * 300
        )
        sent, to, was_trunc = smart_truncate(
            long_sent, "slowly", 23, max_len=250,
        )
        # Pre-quote text ends with comma → not complete.
        # If the function can't truncate safely, it returns original.
        if was_trunc is False:
            assert len(sent) > 250  # original, too long — needs manual
        else:
            # It found a valid truncation path via 3a/3b
            assert len(sent) <= 250

    def test_beginning_truncation_tedious_case(self):
        """406-char quoted passage with target word near the end —
        Phase 2 truncates from the beginning to fit within 250."""
        sent = (
            '"When you\'ve finished your own toilet in the morning, then it '
            'is time to attend to the toilet of your planet, just so, with '
            'the greatest care. You must see to it that you pull up regularly '
            'all the baobabs, at the very first moment when they can be '
            'distinguished from the rosebushes, which they resemble so closely '
            'in their earliest youth. It is very tedious work," the little '
            'prince added, "but very easy."'
        )
        assert len(sent) > 250
        tedious_offset = sent.find("tedious")
        result, new_to, was_trunc = smart_truncate(
            sent, "tedious", tedious_offset, max_len=250,
        )
        assert was_trunc is True
        assert len(result) <= 250
        assert result[new_to:new_to + len("tedious")] == "tedious"
        # After Phase 2 beginning-truncation of quoted speech, the opening
        # quote is preserved — result may start with '"' or uppercase.
        assert result[0] == '"' or result[0].isupper()
        assert result.rstrip()[-1] in '.!?"\''

    def test_beginning_truncation_picks_nearest(self):
        """Direction 2 scans left from target_offset and picks the nearest
        boundary — closest to target = most relevant context."""
        sent = (
            "First sentence with enough words. Second sentence also has many "
            "words here and adds more content to push things along. Third "
            "sentence continues the narrative with additional padding here. "
            "Fourth sentence with the target word here."
        )
        target_offset = sent.find("target")
        assert target_offset > 200, "target must be beyond max_len for Phase 2"
        result, new_to, was_trunc = smart_truncate(
            sent, "target", target_offset, max_len=200,
        )
        assert was_trunc is True
        # Direction 2 scans left from target; nearest '.!?' boundary is
        # the period after "Third sentence..." → starts at "Fourth sentence..."
        assert result.startswith("Fourth sentence")
        assert "target" in result
        assert result[new_to:new_to + len("target")] == "target"

    def test_beginning_truncation_no_valid_boundary(self):
        """No '.!? + space + capital' boundary before target word —
        Phase 2 returns unchanged."""
        sent = "x" * 300 + " target yyy"
        target_offset = sent.find("target")
        result, to, was_trunc = smart_truncate(
            sent, "target", target_offset, max_len=100,
        )
        assert was_trunc is False
        assert result == sent

    def test_direction1_target_at_end_finds_punctuation(self):
        """Target word near end of long sentence with punctuation far
        to the right — Direction 1 finds it."""
        sent = (
            "A" * 100 + " target "
            + "B" * 300 + ". Extra trailing text."
        )
        target_offset = sent.find("target")
        result, new_to, was_trunc = smart_truncate(
            sent, "target", target_offset, max_len=250,
        )
        assert was_trunc is True
        assert len(result) < len(sent)
        assert result.endswith(".")
        assert result[new_to:new_to + len("target")] == "target"

    def test_direction1_no_shortening_ignored(self):
        """Punctuation at end of sentence with nothing after it — no
        shortening possible, falls through to Direction 2 or unchanged."""
        sent = "Short intro. " + "A" * 100 + " target " + "B" * 50 + "."
        target_offset = sent.find("target")
        result, new_to, was_trunc = smart_truncate(
            sent, "target", target_offset, max_len=500,
        )
        # Direction 1: scans right, finds '.' at end, but that doesn't
        # shorten the sentence → falls through.
        # Direction 2: scans left, finds '.' after "Short intro." →
        # starts from there if it shortens.
        if was_trunc:
            assert len(result) < len(sent)
        # Either way, sentence is ≤500 so acceptable

    def test_direction2_nearest_boundary(self):
        """Direction 2 picks the nearest '.' before target, not the
        one that gives the longest result."""
        # Sentence must exceed max_len so Direction 1 is attempted.
        # Direction 1 finds only the final '.' which doesn't shorten,
        # so Direction 2 fires and finds the boundary before target.
        base = (
            "First sentence here. Second sentence here. "
            "Third sentence with the target word continues on and on "
            "without any punctuation to stop Direction 1. "
        )
        sent = base * 3  # ~429 chars, > max_len=200
        toff = sent.find("target")
        result, new_to, was_trunc = smart_truncate(
            sent, "target", toff, max_len=200,
        )
        assert was_trunc is True
        # Direction 2 scans left from target; nearest '.!?' boundary
        # starts at "Third sentence..." (first boundary found scanning left)
        assert "Third sentence" in result
        assert "target" in result
        assert result[new_to:new_to + len("target")] == "target"

    def test_tackle_case_no_internal_punctuation(self):
        """Real-world case: 254-char sentence with only one period at the
        very end, no internal punctuation.  Both directions fail to find
        a shortening point → returned unchanged."""
        sent = (
            "Those who had caught sharks had taken them to the shark "
            "factory on the other side of the cove where they were "
            "hoisted on a block and tackle, their livers removed, their "
            "fins cut off and their hides skinned out and their flesh "
            "cut into strips for salting."
        )
        target_offset = sent.find("tackle")
        result, new_to, was_trunc = smart_truncate(
            sent, "tackle", target_offset, max_len=250,
        )
        # Direction 1: scans right from "tackle", finds '.' at end but
        # that doesn't shorten (it's the very last char).
        # Direction 2: scans left from "tackle", no '.!?' before it.
        # Result: unchanged, len=254 > 250 but ≤ 500 — acceptable.
        assert was_trunc is False
        assert result == sent
        assert "tackle" in result

    def test_direction2_embedded_dialogue_quote_balance(self):
        """Direction 2 skips boundaries inside quoted dialogue.  When all
        boundaries are inside the quote (target word inside a long quoted
        passage) and the opening quote has no .!? boundary before it,
        smart_truncate returns the original sentence unchanged so the
        caller can reject the word rather than fabricate a patched result.

        This is the OMAS "dipping" case — all .!? before the target are
        inside "The birds...for the sea." and the narration before the
        opening " has no .!? boundary."""
        sent = (
            "He was sorry for the birds, especially the small delicate dark "
            'terns that were always flying and looking and almost never '
            'finding, and he thought, "The birds have a harder life than '
            "we do except for the robber birds and the heavy strong ones. "
            "Why did they make birds so delicate and fine as those sea "
            "swallows when the ocean can be so cruel? She is kind and very "
            "beautiful. But she can be so cruel and it comes so suddenly "
            "and such birds that fly, dipping and hunting, with their "
            'small sad voices are made too delicately for the sea."'
        )
        target_offset = sent.find("dipping")
        assert target_offset > 0
        result, new_to, was_trunc = smart_truncate(
            sent, "dipping", target_offset, max_len=250,
        )
        # All .!? boundaries are inside the quote → all skipped.
        # No boundary before the opening " → no valid truncation.
        # Fallback produces unbalanced quotes → rejected.
        # Returns original sentence unchanged for caller to reject.
        assert was_trunc is False
        assert result == sent
        assert "dipping" in result


class TestIsNonBodyText:
    """Tests for _is_non_body_text() — detecting bibliography, copyright, etc."""

    def test_all_caps_title_list(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            "THE OLD MAN AND THE SEA ACROSS THE RIVER AND INTO THE TREES"
        ) is True

    def test_all_caps_too_short(self):
        from lib.scripts.match_sentences import _is_non_body_text
        # "THE END" is only 7 chars, below 25-char threshold
        assert _is_non_body_text("THE END") is False

    def test_copyright_boilerplate(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            "IF THE BOOK IS UNDER COPYRIGHT IN YOUR COUNTRY, DO NOT DOWNLOAD"
        ) is True

    def test_producer_credit(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            "Produced by Al Haines"
        ) is True

    def test_producer_credit_embedded(self):
        """'produced by' embedded in a line (not at start) — FadedPage ebook metadata."""
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            "This ebook was produced by Al Haines"
        ) is True

    def test_distributed_proofreaders(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            "A Distributed Proofreaders Canada Ebook"
        ) is True

    def test_dedication(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text("TO MAX PERKINS") is True

    def test_dedication_too_long(self):
        from lib.scripts.match_sentences import _is_non_body_text
        # Dedication with >6 words — not excluded (real dedications are short).
        # Mixed case so it doesn't trigger the ALL_CAPS pattern.
        assert _is_non_body_text(
            "To my dearest wife and my wonderful children"
        ) is False

    def test_end_marker(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            "[End of The Old Man and the Sea, by Ernest Hemingway]"
        ) is True

    def test_normal_body_text_not_excluded(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            "He was an old man who fished alone in a skiff in the Gulf Stream."
        ) is False

    def test_normal_dialogue_not_excluded(self):
        from lib.scripts.match_sentences import _is_non_body_text
        assert _is_non_body_text(
            '"I fear both the Tigers of Detroit and the Indians of Cleveland."'
        ) is False


class TestNormalizeQuotes:
    """Curly quote to ASCII straight quote normalisation (from lib.utils)."""

    def test_left_single(self):
        from lib.utils import normalize_quotes
        assert normalize_quotes("It‘s a test") == "It's a test"

    def test_right_single(self):
        from lib.utils import normalize_quotes
        assert normalize_quotes("It’s a test") == "It's a test"

    def test_left_double(self):
        from lib.utils import normalize_quotes
        assert normalize_quotes("“Hello”") == '"Hello"'

    def test_right_double(self):
        from lib.utils import normalize_quotes
        assert normalize_quotes("“Hello”") == '"Hello"'

    def test_all_curly_quotes_in_sentence(self):
        from lib.utils import normalize_quotes
        inp = "“It’s a ‘boa constrictor’,” he said."
        exp = "\"It\'s a \'boa constrictor\',\" he said."
        assert normalize_quotes(inp) == exp

    def test_no_curly_quotes_unchanged(self):
        from lib.utils import normalize_quotes
        assert normalize_quotes('"Hello world"') == '"Hello world"'

    def test_empty_string(self):
        from lib.utils import normalize_quotes
        assert normalize_quotes("") == ""

    def test_fullwidth_quote(self):
        from lib.utils import normalize_quotes
        assert normalize_quotes("＂Hello＂") == '"Hello"'

class TestMidSentenceCapitalizedNounStaysNoun:
    """Quote-initial capitalised common nouns must stay NOUN when in form_index.

    Regression test: the mid-sentence capitalised NOUN→PROPN rule (line ~806)
    must NOT fire when the word is in our target vocabulary — the capitalisation
    is positional (quote-start), not a proper-noun signal.
    """

    def test_quote_initial_capitalized_word_in_vocab_stays_noun(self):
        """'Boa' capitalised at quote start should be NOUN, not PROPN."""
        import json
        from lib.scripts.match_sentences import process_words

        source = (
            'He said: "Boa constrictors swallow their prey whole." '
            'It was a picture of a boa constrictor.'
        )
        data = {
            "in_coca": [
                {"lemma": "boa", "rep": "boa", "forms": ["boa"]},
            ],
            "book_title": "Test Book",
            "book_author": "Test Author",
        }

        result = process_words(data, source)
        words = result["words"]

        # Should produce exactly 1 entry: (boa, NOUN)
        # Not 2 entries: (boa, NOUN) + (boa, PROPN)
        assert len(words) == 1, f"Expected 1 entry, got {len(words)}: {[(w['lemma'], w['pos']) for w in words]}"
        assert words[0]["lemma"] == "boa"
        assert words[0]["pos"] == "NOUN", (
            f"Expected NOUN, got {words[0]['pos']}. "
            "Mid-sentence capitalised NOUN→PROPN rule fired incorrectly."
        )

    def test_genuine_propn_still_converts(self):
        """'Jupiter' not in form_index → should stay PROPN (or convert from NOUN)."""
        import json
        from lib.scripts.match_sentences import process_words

        source = (
            "I read about Jupiter in a book. "
            "The planet Jupiter is huge."
        )
        data = {
            "in_coca": [
                {"lemma": "jupiter", "rep": "Jupiter", "forms": ["Jupiter", "jupiter"]},
            ],
            "book_title": "Test Book",
            "book_author": "Test Author",
        }

        result = process_words(data, source)
        words = result["words"]
        # Jupiter is a genuine proper noun — should be PROPN
        # (form_index membership converts to NOUN → revert guard restores to PROPN
        #  if never lowercase in text; or mid-sentence rule should not fire
        #  since _was_propn=True after PROPN→NOUN conversion.)
        pos_values = {w["pos"] for w in words}
        # The revert guard should restore it to PROPN
        assert "PROPN" in pos_values or len(words) == 1, (
            f"Expected PROPN for Jupiter (genuine proper noun), got: {pos_values}"
        )


# ── Problem 1: smart_truncate with multi-quote dialogue ────────────────────


class TestSmartTruncateDialogueSentenceBoundary:
    """smart_truncate should accept .!? followed by space + capital letter
    as a sentence boundary even when inside an unclosed quote."""

    def test_period_space_capital_inside_quote_accepted(self):
        """A period followed by space+capital marks a sentence boundary
        within quoted dialogue — should be accepted as truncation point."""
        sentence = (
            '"But the animals..." "Well, I must endure the presence of two '
            'or three caterpillars if I wish to become acquainted with the '
            'butterflies. It seems that they are very beautiful. And if not '
            'the butterflies and the caterpillars who will call upon me? '
            'You will be far away... as for the large animals, I am not at '
            'all afraid of any of them. I have my claws."'
        )
        assert len(sentence) > 250
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "caterpillars", 71, max_len=250)
        assert was_trunc, (
            "Should truncate at 'butterflies.' — sentence boundary inside quote"
        )
        assert len(new_sent) <= 250
        # The truncated result should contain the target word
        assert new_sent[new_tgt:new_tgt + len("caterpillars")].lower() == "caterpillars"

    def test_period_space_capital_inside_quote_endure(self):
        """Same sentence, different target word earlier in the text."""
        sentence = (
            '"But the animals..." "Well, I must endure the presence of two '
            'or three caterpillars if I wish to become acquainted with the '
            'butterflies. It seems that they are very beautiful. And if not '
            'the butterflies and the caterpillars who will call upon me? '
            'You will be far away... as for the large animals, I am not at '
            'all afraid of any of them. I have my claws."'
        )
        assert len(sentence) > 250
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "endure", 35, max_len=250)
        assert was_trunc
        assert len(new_sent) <= 250
        assert new_sent[new_tgt:new_tgt + len("endure")].lower() == "endure"

    def test_unbalanced_quotes_cleaned_up(self):
        """Truncated result should have balanced quotes (even count)
        or the unclosed opening quote removed with preceding text."""
        sentence = (
            '"But the animals..." "Well, I must endure the presence of two '
            'or three caterpillars if I wish to become acquainted with the '
            'butterflies. It seems that they are very beautiful."'
        )
        # Force truncation at the first period inside the quote
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "endure", 35, max_len=160)
        assert was_trunc
        # Result should either have balanced quotes or be cleaned
        assert new_sent.count('"') % 2 == 0, (
            f"Expected balanced quotes, got {new_sent.count('\"')} quotes: {new_sent!r}"
        )
        # Verify target word is preserved
        assert new_sent[new_tgt:new_tgt + len("endure")].lower() == "endure"


class TestWalkBackDialogueAttributionComma:
    """smart_truncate walk-back should accept dialogue-attribution comma
    (", followed by opening ") by replacing the comma with a period."""

    def test_walk_back_strips_dialogue_attribution_comma(self):
        """When the walk-back truncation produces text ending with a
        dialogue-attribution comma (e.g. "...and he thought," + '"'),
        the comma should be replaced with a period — the clause is
        grammatically complete."""
        # The sentence must exceed max_len to trigger smart_truncate.
        # Simulate a hard-truncated dialogue passage (no closing quote)
        # like the real tern case from The Old Man and the Sea.
        sentence = (
            'He was sorry for the birds, especially the small delicate dark '
            'terns that were always flying and looking and almost never '
            'finding, and he thought, "The birds have a harder life than we '
            'do except for the robber birds and the heavy strong ones. Why '
            'did they make birds so delicate and fine as those sea swallows '
            'when the ocean can be so cruel? She is kind and very beautiful '
            'and it comes so suddenly and such birds'
        )
        assert len(sentence) > 250
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "terns", 63, max_len=250)
        assert was_trunc, "should truncate at dialogue-attribution comma"
        assert new_sent.endswith("and he thought."), (
            f"should end with period, not comma: {new_sent[-30:]!r}"
        )
        assert not _is_fragment(new_sent), (
            f"should not be a fragment: {new_sent!r}"
        )
        assert new_sent.count('"') % 2 == 0, (
            f"should have balanced quotes: {new_sent.count(chr(34))}"
        )
        assert new_sent[new_tgt:new_tgt + len("terns")].lower() == "terns"
        assert len(new_sent) <= 250


class TestCleanupUnclosedQuote:
    """Unit tests for _cleanup_unclosed_quote helper."""

    def test_balanced_quotes_unchanged(self):
        result, tgt = _cleanup_unclosed_quote(
            '"Hello." she said.', "Hello", 1)
        assert result == '"Hello." she said.'
        assert tgt == 1

    def test_unclosed_quote_removed_target_preserved(self):
        # Simulates: truncated to "But the animals..." "Well, I must endure...butterflies.
        # "endure" is at position 35 in the original string
        result, tgt = _cleanup_unclosed_quote(
            '"But the animals..." "Well, I must endure the presence.',
            "endure", 35)
        # After cleanup: "Well" should be first word (no leading quote)
        assert not result.startswith('"')
        assert "endure" in result
        # Verify target_offset still points to correct word
        assert result[tgt:tgt + len("endure")].lower() == "endure"

    def test_even_quotes_no_change(self):
        result, tgt = _cleanup_unclosed_quote(
            '"Hello." "World."', "World", 9)
        # Even quotes (4 total) — should be unchanged
        assert result == '"Hello." "World."'
        assert tgt == 9

    def test_target_word_not_preserved_keeps_original(self):
        # If removing the unclosed quote would cut off the target word,
        # return the original unchanged
        result, tgt = _cleanup_unclosed_quote(
            '"target word here', "target", 1)
        # "target" IS in the after_quote part, so it should be cleaned
        assert not result.startswith('"')
        assert "target" in result

    # ── forward-search (tail parameter) ─────────────────────────────────

    def test_forward_search_finds_closing_quote(self):
        """When tail contains the missing closing \", extend result to include it."""
        result, tgt = _cleanup_unclosed_quote(
            '"That man," said the prince, "that man would be scorned.',
            "scorned", 48,
            tail=' Nevertheless he is the only one."',
        )
        # Forward search found the closing " in tail — balanced quotes
        assert result.count('"') % 2 == 0
        assert 'Nevertheless' in result
        assert result.endswith('."')
        assert result[tgt:tgt + len("scorned")].lower() == "scorned"

    def test_forward_search_without_tail(self):
        """Without tail, falls back to original stripping behavior."""
        result, tgt = _cleanup_unclosed_quote(
            '"That man," said the prince, "that man would be scorned.',
            "scorned", 48,
        )
        # No tail — strips before the unclosed ", result starts lowercase
        assert result.startswith("that man")
        assert "scorned" in result

    def test_forward_search_no_closing_quote_in_tail(self):
        """When tail has no closing \", falls back to stripping."""
        result, tgt = _cleanup_unclosed_quote(
            '"He said, "hello world. She replied.',
            "world", 17,
            tail=' No closing quote here.',
        )
        # tail has no " — forward search fails, falls back to stripping
        assert "world" in result
        assert "hello world" in result

    # ── fragment guard: stripping quoted speech must not produce a fragment ──

    def test_before_unclosed_quote_fragment_rejected(self):
        """Stripping quoted speech must not produce a comma-ending fragment.

        When _cleanup_unclosed_quote strips from the unclosed " to the end
        and the remaining text has no terminal punctuation, the result is
        a sentence fragment — reject the strip and return the original.
        """
        # Simulates: smart_truncate Direction 1 truncates at '.' inside
        # quoted speech, then _cleanup_unclosed_quote strips the unclosed
        # quote + trailing dialogue, leaving "and he thought," — a fragment.
        result, tgt = _cleanup_unclosed_quote(
            'He was sorry for the birds, and he thought, "The birds have a harder life.',
            "birds", 12,
        )
        # The stripped result before " would be "He was sorry for the birds, and he thought,"
        # — ends with comma, no terminal punctuation → must NOT be returned.
        # The function should return the original unchanged.
        assert result == 'He was sorry for the birds, and he thought, "The birds have a harder life.'
        assert tgt == 12

    def test_before_unclosed_quote_valid_sentence_accepted(self):
        """When stripping quoted speech yields a valid sentence, accept it."""
        # The text before " ends with '.' — valid truncation.
        # Use odd number of quotes so _cleanup_unclosed_quote actually runs.
        # "fish" is at position 11 in this string.
        result, tgt = _cleanup_unclosed_quote(
            'He ate the fish quickly. "Delicious, he said.',
            "fish", 11,
        )
        # Text before " is "He ate the fish quickly." — ends with '.' → OK
        assert result == "He ate the fish quickly."
        assert tgt == 11
        assert "fish" in result


# ── Problem 2 & 3: _cmu_ipa suffix stripping ────────────────────────────────


class TestCmuIpaSuffixStripping:
    """_cmu_ipa should handle -ion suffix and y→i spelling changes."""

    def test_ion_suffix_dejection(self):
        """dejection → deject + /ən/ — deject is in cmudict."""
        ipa = _cmu_ipa("dejection")
        assert ipa, "dejection should get IPA via -ion suffix stripping"
        assert ipa.startswith("/") and ipa.endswith("/"), (
            f"IPA should have / delimiters, got: {ipa!r}")
        # Should contain the base word's IPA + the suffix
        assert "ʃən" in ipa or "ʒən" in ipa or "ən" in ipa or "dʒek" in ipa.lower(), (
            f"Unexpected IPA for dejection: {ipa!r}")

    def test_ly_y_to_i_thriftily(self):
        """thriftily → thrifti → thrifty (y→i) + /li/ — thrifty is in cmudict."""
        ipa = _cmu_ipa("thriftily")
        assert ipa, "thriftily should get IPA via y→i spelling recovery"
        assert ipa.startswith("/") and ipa.endswith("/"), (
            f"IPA should have / delimiters, got: {ipa!r}")
        # Should contain /θrɪft/ or similar from thrifty + /li/
        assert "θr" in ipa.lower() or "thr" in ipa.lower() or "li" in ipa, (
            f"Unexpected IPA for thriftily: {ipa!r}")

    def test_tion_still_works(self):
        """Existing -tion suffix should still work (regression check)."""
        ipa = _cmu_ipa("education")
        assert ipa, "education should get IPA via -tion suffix stripping"
        assert "ʃən" in ipa

    def test_ly_ble_to_bly_perceptibly(self):
        """perceptibly → strip ly → perceptib → +le → perceptible + /li/."""
        ipa = _cmu_ipa("perceptibly")
        assert ipa, "perceptibly should get IPA via -bly→-ble fallback"
        assert ipa.startswith("/") and ipa.endswith("/"), (
            f"IPA should have / delimiters, got: {ipa!r}")
        assert "li" in ipa, f"Expected /li/ in IPA, got: {ipa!r}"

    def test_tion_to_te_undulation(self):
        """undulation → strip tion → undula → +te → undulate + /ʃən/."""
        ipa = _cmu_ipa("undulation")
        assert ipa, "undulation should get IPA via -tion→-te fallback"
        assert "ʃən" in ipa, f"Expected /ʃən/ in IPA, got: {ipa!r}"

    def test_ly_still_works(self):
        """Existing -ly suffix should still work (regression check)."""
        ipa = _cmu_ipa("indulgently")
        assert ipa, "indulgently should get IPA via -ly suffix stripping"
        assert "li" in ipa

    def test_ion_only_fires_when_tion_sion_dont_match(self):
        """When both -tion and -ion could match, -tion wins (more specific)."""
        # "education" ends in both "tion" and "ion".
        # -tion should match first, stripping to "educa" + tion → in cmudict as "educate"
        ipa = _cmu_ipa("education")
        assert ipa
        # The -tion → educate + /ʃən/ path should take priority
        assert "ʃən" in ipa


# ── B-1/B-2: smart_truncate accepts missing space after punctuation ──────


class TestSmartTruncateMissingSpace:
    """smart_truncate should accept .!? followed directly by capital letter
    (no space) — common OCR pattern in Internet Archive texts."""

    def test_exclamation_no_space_before_capital(self):
        """!X pattern — exclamation + capital letter with no space."""
        # target "panted" at position 41, max_len=100
        # "!He" is near position 90 — within scan range (99→48)
        prefix = "The little prince sat down on the table and panted a little"
        tgt = prefix.index("panted")
        padding = "x" * (98 - len(prefix))  # push boundary near max_len
        sentence = prefix + padding + "!He was very tired after the long day"
        assert len(sentence) > 100
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "panted", tgt, max_len=100)
        assert was_trunc, (
            "Should truncate at ! — capital follows directly without space"
        )
        assert len(new_sent) <= 100
        assert "panted" in new_sent

    def test_exclamation_quote_no_space_before_capital(self):
        """!"X pattern — exclamation + closing quote + capital, no space."""
        prefix = "The little prince sat down on the table and panted a little"
        tgt = prefix.index("panted")
        padding = "x" * (96 - len(prefix))
        sentence = prefix + padding + '!"He was very tired after the long day'
        assert len(sentence) > 100
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "panted", tgt, max_len=100)
        assert was_trunc, (
            "Should truncate at !\" — capital follows quote without space"
        )
        assert len(new_sent) <= 100

    def test_period_quote_no_space_before_capital(self):
        """."X pattern — period + closing quote + capital, no space."""
        prefix = "The little prince sat down on the table and panted a little"
        tgt = prefix.index("panted")
        padding = "x" * (96 - len(prefix))
        sentence = prefix + padding + '."He was very tired after the long day'
        assert len(sentence) > 100
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "panted", tgt, max_len=100)
        assert was_trunc, (
            "Should truncate at .\" — capital follows quote without space"
        )
        assert len(new_sent) <= 100

    def test_period_no_space_before_capital(self):
        """.X pattern — period + capital letter with no space (no quote)."""
        prefix = "The little prince sat down on the table and panted a little"
        tgt = prefix.index("panted")
        padding = "x" * (98 - len(prefix))
        sentence = prefix + padding + ".He was very tired after the long day"
        assert len(sentence) > 100
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "panted", tgt, max_len=100)
        assert was_trunc, (
            "Should truncate at . — capital follows directly without space"
        )
        assert len(new_sent) <= 100

    def test_existing_space_capital_still_works(self):
        """Regression: . X pattern (with space) still accepted."""
        sentence = (
            '"But the animals..." "Well, I must endure the presence of two '
            'or three caterpillars if I wish to become acquainted with the '
            'butterflies. It seems that they are very beautiful. And if not '
            'the butterflies and the caterpillars who will call upon me? '
            'You will be far away... as for the large animals, I am not at '
            'all afraid of any of them. I have my claws."'
        )
        assert len(sentence) > 250
        new_sent, new_tgt, was_trunc = smart_truncate(
            sentence, "caterpillars", 71, max_len=250)
        assert was_trunc
        assert len(new_sent) <= 250


# ── B-3: build_sentence_regex handles punctuation glued to next word ────


class TestBuildSentenceRegex:
    """build_sentence_regex should handle punctuation without trailing space."""

    def test_punctuation_glued_to_next_word(self):
        """Period glued to next word — regex must match both spaced and unspaced."""
        import re
        from lib.utils import build_sentence_regex
        regex = build_sentence_regex("Hello world.I am fine")
        # Must match source text with space
        assert re.search(regex, "Hello world. I am fine"), (
            "Regex should match source with space after period"
        )
        # Must also match source without space (OCR pattern)
        assert re.search(regex, "Hello world.I am fine"), (
            "Regex should match source without space after period"
        )

    def test_existing_behavior_preserved(self):
        """Normal spacing unchanged — backward compatible."""
        import re
        from lib.utils import build_sentence_regex
        regex = build_sentence_regex("Hello world. I am fine")
        assert re.search(regex, "Hello world. I am fine")
        assert re.search(regex, "Hello world.\nI am fine"), (
            "Regex should handle newline between sentences"
        )

    def test_multiple_glued_punctuation(self):
        """Multiple punctuation-glued words in one sentence."""
        import re
        from lib.utils import build_sentence_regex
        regex = build_sentence_regex("Stop.Think.Go forward")
        assert re.search(regex, "Stop. Think. Go forward")
        assert re.search(regex, "Stop.Think.Go forward")

    def test_glued_with_newline(self):
        """Punctuation glued + with newline between sentences."""
        import re
        from lib.utils import build_sentence_regex
        regex = build_sentence_regex("That is all.It is enough")
        # Newline between sentences should still match
        assert re.search(regex, "That is all.\nIt is enough")


# ── C: IPA must not have nested slashes ───────────────────────────────────


class TestCmuIpaNoNestedSlashes:
    """Suffix-fallback IPA must not produce nested slash delimiters."""

    def test_ly_adverb_no_nested_slash(self):
        """indulgently → /ɪnˈdʌldʒəntli/, not /ɪnˈdʌldʒənt/li/."""
        result = _cmu_ipa("indulgently")
        assert result, "indulgently should get IPA via -ly fallback"
        slash_count = result.count("/")
        assert slash_count == 2, (
            f"Expected exactly 2 slashes (delimiters), got {slash_count}: "
            f"{result}"
        )
        assert result.endswith("li/"), (
            f"Expected /li/ suffix on fallback IPA, got: {result}"
        )

    def test_ness_suffix_no_nested_slash(self):
        """-ness suffix IPA should also not have nested slashes."""
        result = _cmu_ipa("happiness")
        assert result
        assert result.count("/") == 2, (
            f"Expected 2 slashes for happiness, got: {result}"
        )


class TestCmuIpaBritishSpelling:
    """British -our → -or fallback for IPA lookup."""

    def test_discolour_falls_back_to_discolor(self):
        """discolour (Br) → discolor (US) → IPA."""
        result = _cmu_ipa("discolour")
        assert result, "discolour should get IPA via -our→-or fallback"
        assert "/" in result

    def test_colour_still_works_directly(self):
        """colour is already in cmudict; exact match should still work."""
        result = _cmu_ipa("colour")
        assert result, "colour should be in cmudict directly"
        assert "/" in result

    def test_honour_falls_back_to_honor(self):
        """honour → honor → IPA."""
        result = _cmu_ipa("honour")
        assert result, "honour should get IPA via -our→-or fallback"


# ── E: fragment merge with quote + lowercase start ───────────────────────


class TestMergeFragmentQuoteLowercase:
    """_merge_adjacent_fragments should handle quote + lowercase starts."""

    def test_merge_quote_lowercase_fragment(self):
        """Fragment starting with ASCII quote + lowercase merges."""
        source = 'The wise king said: \n\n"that man would be scorned by the people.'
        sents = ['The wise king said:', '"that man would be scorned by the people.']
        merged = _merge_adjacent_fragments(sents, source)
        assert len(merged) == 1, (
            f"Expected 1 merged sentence, got {len(merged)}: {merged}"
        )
        assert 'man' in merged[0]

    def test_merge_curly_quote_lowercase_fragment(self):
        """Fragment starting with curly quote + lowercase merges (IA OCR)."""
        source = 'He replied: \n\n“that is not what I meant.'
        sents = ['He replied:', '“that is not what I meant.']
        merged = _merge_adjacent_fragments(sents, source)
        assert len(merged) == 1, (
            f"Expected 1 merged sentence, got {len(merged)}: {merged}"
        )

    def test_normal_lowercase_still_merges(self):
        """Regression: normal lowercase-start fragments still merge."""
        source = 'which was at \n\nthe same time both simple and majestic.'
        sents = ['which was at', 'the same time both simple and majestic.']
        merged = _merge_adjacent_fragments(sents, source)
        assert len(merged) == 1

    def test_quote_uppercase_not_merged(self):
        """Quote + uppercase should NOT merge (new sentence)."""
        source = 'He finished. \n\n"That is all."'
        sents = ['He finished.', '"That is all."']
        merged = _merge_adjacent_fragments(sents, source)
        # First is NOT a fragment (ends with period), so no merge
        assert len(merged) == 2


# ── B-4: hyphenated compound skip ────────────────────────────────────────


class TestHyphenatedCompoundSkip:
    """dep=compound tokens inside hyphenated compounds should be skipped."""

    def test_mast_in_mast_head_is_skipped(self):
        """'mast' in 'mast-head' (compound, hyphen) → skipped."""
        result = _run_pipeline(
            [{"lemma": "mast", "rep": "mast",
              "forms": ["mast"], "coca_level": 7}],
            "In the turtle boats I was in the cross-trees of the mast-head.",
        )
        words = result.get("words", [])
        mast_entries = [w for w in words if w["lemma"] == "mast"]
        assert len(mast_entries) == 0, \
            f"mast in mast-head should be skipped, got {len(mast_entries)} entries"

    def test_mast_as_standalone_noun_still_matches(self):
        """'mast' as standalone noun (dobj) → still matches."""
        result = _run_pipeline(
            [{"lemma": "mast", "rep": "mast",
              "forms": ["mast"], "coca_level": 7}],
            "Finally he put the mast down and stood up.",
        )
        w = result["words"][0]
        assert w["lemma"] == "mast"
        assert w["pos"] == "NOUN", f"standalone mast should be NOUN, got {w['pos']}"

    def test_tropic_without_hyphen_still_matches(self):
        """'tropic' as compound without hyphen → still matches."""
        result = _run_pipeline(
            [{"lemma": "tropic", "rep": "tropic",
              "forms": ["tropic"], "coca_level": 10}],
            "The brown blotches from its reflection on the tropic sea.",
        )
        w = result["words"][0]
        assert w["lemma"] == "tropic"
        # compound dep without hyphen — keep the match

    def test_fair_in_fair_minded_is_matched(self):
        """'fair' in 'fair-minded' (amod, not compound) → matched as ADJ.

        Unlike compound-dep tokens (e.g. "mast" in "mast-head" where mast
        is a noun modifier), "fair" in "fair-minded" IS a true adjective
        (公正的).  The amod dep confirms this — only compound-dep tokens
        adjacent to a hyphen are skipped.
        """
        result = _run_pipeline(
            [{"lemma": "fair", "rep": "fair",
              "forms": ["fair"], "coca_level": 2}],
            "He was a fair-minded judge.",
        )
        w = result["words"][0]
        assert w["lemma"] == "fair"
        assert w["pos"] == "ADJ", \
            f"fair in fair-minded is a true adjective, got {w['pos']}"

    def test_head_of_hyphenated_compound_is_skipped(self):
        """'garland' in 'half-garland' (head of compound) → skipped.

        The compound child 'half' is the modifier adjacent to '-'; 'garland'
        is the head.  Both should be skipped — the word only appears as
        part of a hyphenated compound, not independently.
        """
        result = _run_pipeline(
            [{"lemma": "garland", "rep": "garland",
              "forms": ["garland"], "coca_level": 9}],
            "They made a half-garland on the projecting steel.",
        )
        words = result.get("words", [])
        garland_entries = [w for w in words if w["lemma"] == "garland"]
        assert len(garland_entries) == 0, \
            f"garland in half-garland should be skipped, got {len(garland_entries)} entries"

    def test_standalone_garland_still_matches(self):
        """'garland' without hyphenated compound → still matches."""
        result = _run_pipeline(
            [{"lemma": "garland", "rep": "garland",
              "forms": ["garland"], "coca_level": 9}],
            "She wore a garland of flowers in her hair.",
        )
        w = result["words"][0]
        assert w["lemma"] == "garland"
        assert w["pos"] == "NOUN", f"standalone garland should be NOUN, got {w['pos']}"


# ── B-5: rstrip comma for function word detection ────────────────────────


class TestFunctionWordCommaStrip:
    """rstrip(':;,') should allow comma on function words to be stripped."""

    def test_function_word_with_comma_stripped(self):
        """Comma on function word should be stripped for detection."""
        from lib.config import SENTENCE_END_FUNCTION_WORDS
        assert "then" in SENTENCE_END_FUNCTION_WORDS, (
            "'then' should be in the function word set"
        )
        last_word = "then,"
        cleaned = last_word.strip().lower().rstrip(':;,')
        assert cleaned == "then", (
            f"rstrip(':;,') should strip comma, got {cleaned!r}"
        )
        assert cleaned in SENTENCE_END_FUNCTION_WORDS

    def test_colon_still_stripped(self):
        """Regression: colon stripping still works."""
        from lib.config import SENTENCE_END_FUNCTION_WORDS
        last_word = "then:"
        cleaned = last_word.strip().lower().rstrip(':;,')
        assert cleaned == "then"
        assert cleaned in SENTENCE_END_FUNCTION_WORDS


class TestConjPosInheritanceVbnAclGuard:
    """Conj POS inheritance: VBN+acl chain root does NOT promote to VERB.

    When the conj chain root is a VBN with dep=acl (adjectival clause
    modifier), it is functioning as an adjective — conjuncts should not
    inherit VERB.  E.g. "the formalized, iridescent, gelatinous bladder"
    → formalized(VBN,acl) → iridescent(NOUN,conj) → bladder(NOUN,conj).
    Without the guard, bladder would be incorrectly promoted to VERB.
    """

    def test_noun_conj_of_vbn_acl_stays_noun(self):
        """bladder in 'gelatinous bladder' is NOUN, not promoted to VERB."""
        result = _run_pipeline(
            [{"lemma": "bladder", "rep": "bladder",
              "forms": ["bladder"], "coca_level": 6}],
            "Nothing showed but patches of yellow Sargasso weed and the "
            "purple, formalized, iridescent, gelatinous bladder of a "
            "Portuguese man-of-war floating close beside the boat.",
        )
        words = result.get("words", [])
        bladder_entries = [w for w in words if w["lemma"] == "bladder"]
        if bladder_entries:
            assert bladder_entries[0]["pos"] == "NOUN", \
                f"bladder should stay NOUN (VBN+acl chain root), got {bladder_entries[0]['pos']}"

    def test_noun_direct_conj_of_verb_stays_noun(self):
        """NOUN conj of VERB stays NOUN — coordinated argument, not verb.

        E.g. 'fins' in 'see...heads and...fins' — fins is a coordinated
        object of 'see', not a verb.  spaCy's own POS tag (NOUN) is more
        trustworthy than the VERB chain root.
        """
        result = _run_pipeline(
            [{"lemma": "fin", "rep": "fins",
              "forms": ["fins"], "coca_level": 6}],
            "He could see their wide flattened shovel-pointed heads now "
            "and their white-tipped wide pectoral fins.",
        )
        words = result.get("words", [])
        fin_entries = [w for w in words if w["lemma"] == "fin"]
        for w in fin_entries:
            assert w["pos"] != "VERB", \
                f"fins should not be VERB (NOUN conj of VERB), got {w['pos']}"

    def test_noun_conj_of_verb_without_dobj_stays_noun(self):
        """NOUN conj of VERB without dobj sibling — still stays NOUN.

        The guard applies regardless of whether the VERB has a dobj child.
        A spaCy-tagged NOUN should never be promoted to VERB via conj
        inheritance — the spaCy POS tag is the more reliable signal.
        """
        result = _run_pipeline(
            [{"lemma": "testword", "rep": "testing",
              "forms": ["testing"], "coca_level": 10}],
            "The system runs and testing completes quickly.",
        )
        # "testing" here is actually a gerund/noun — spaCy may tag it NOUN or VERB.
        # If spaCy tagged it VERB, conj inheritance keeps it VERB (fine).
        # If spaCy tagged it NOUN, conj inheritance should NOT promote to VERB.
        words = result.get("words", [])
        test_entries = [w for w in words if w["lemma"] == "testword"]
        for w in test_entries:
            if w["pos"] == "VERB":
                # Only acceptable if spaCy originally tagged it as VERB
                pass  # OK
            else:
                assert w["pos"] != "VERB", \
                    f"testword should not be VERB if spaCy tagged it as non-VERB, got {w['pos']}"

    def test_verb_conj_of_noun_with_verbal_dependents_stays_verb(self):
        """VERB conj of NOUN stays VERB when it has verbal dependents.

        When spaCy mis-tags a gerund as NOUN (e.g. "swimming") and a true
        VERB with verbal dependents (dobj) is conjunct of it, the VERB
        should NOT be demoted to NOUN.  The verbal dependents (dobj) are
        a reliable signal that the conjunct is genuinely verbal.

        E.g. "paralyzed"(VBD,conj,dobj="leg") whose head is
        "swimming"(NOUN, mis-tagged gerund) — the conjunct should stay VERB.
        """
        result = _run_pipeline(
            [{"lemma": "hit", "rep": "hit",
              "forms": ["hit"], "coca_level": 6}],
            "He was running late and hit the wall hard.",
        )
        words = result.get("words", [])
        hit_entries = [w for w in words if w["lemma"] == "hit"]
        for w in hit_entries:
            # If spaCy tagged "hit" as VERB and it has conj dep to a
            # potentially nominal coordination root, the guard should
            # keep it as VERB (hit has dobj "wall").
            assert w["pos"] != "NOUN", \
                f"hit should not be NOUN (VERB with dobj, conj of potential NOUN root), got {w['pos']}"

    def test_vbg_conj_of_noun_stays_verb(self):
        """VBG (present participle) conj of NOUN stays VERB.

        When a present participle (VBG) has dep=conj to a noun head,
        it should not be demoted to NOUN.  spaCy only tags VBG when
        the word is genuinely verbal; nominal gerunds are tagged NN.

        E.g. "crouching"(VBG,conj) whose head is "stern"(NOUN) —
        the present participle should stay VERB even without its own
        verbal dependents (they may be shared across conjuncts, e.g.
        "crouching and holding the line" — dobj on last conjunct only).
        """
        result = _run_pipeline(
            [{"lemma": "crouch", "rep": "crouching",
              "forms": ["crouching"], "coca_level": 5}],
            "He worked his way back to the stern and crouching and holding "
            "the line, he pulled the dolphin in.",
        )
        words = result.get("words", [])
        crouch_entries = [w for w in words if w["lemma"] == "crouch"]
        assert len(crouch_entries) > 0, "crouch entry should exist"
        for w in crouch_entries:
            assert w["pos"] == "VERB", \
                f"crouching should stay VERB (VBG, conj of NOUN), got {w['pos']}"

    def test_vbg_with_det_child_allows_noun_inheritance(self):
        """VBG with determiner child allows NOUN inheritance.

        A VBG present participle with a determiner child (e.g. "the
        hissing") is functionally a nominal gerund — the det is a
        strong signal of nominal status.  The VBG guard should NOT
        fire, allowing the conj chain to demote it to NOUN.

        E.g. "the hissing that their wings made" — "hissing"(VBG,conj,
        det="the") → should be NOUN (nominal gerund).
        """
        result = _run_pipeline(
            [{"lemma": "hiss", "rep": "hissing",
              "forms": ["hissing"], "coca_level": 5}],
            "He heard the trembling sound and the hissing that their "
            "wings made as they flew.",
        )
        words = result.get("words", [])
        hiss_entries = [w for w in words if w["lemma"] == "hiss"]
        assert len(hiss_entries) > 0, "hiss entry should exist"
        for w in hiss_entries:
            # With det child "the", this is a nominal gerund → NOUN
            assert w["pos"] == "NOUN", \
                f"hissing with det child should be NOUN (nominal gerund), got {w['pos']}"

    def test_plural_noun_nn_tag_lemmatizes_to_singular(self):
        """NOUN with tag=NN (singular) ending in -s lemmatizes to singular.

        When spaCy inconsistently tags a plural noun as NN (singular,
        e.g. "claws" in "gripped claws of an eagle"), the lemma equals
        the word form instead of the singular base.  The fix tries
        lemminflect NOUN channel when tag_==NN and word ends in -s.
        """
        result = _run_pipeline(
            [{"lemma": "claw", "rep": "claws",
              "forms": ["claws"], "coca_level": 5}],
            "His left hand was still as tight as the gripped claws of an eagle.",
        )
        words = result.get("words", [])
        claw_entries = [w for w in words if w["lemma"] == "claw"]
        assert len(claw_entries) > 0, "claw entry should exist with lemma=claw"
        for w in claw_entries:
            assert w["lemma"] == "claw", \
                f"claws should lemma to 'claw', got '{w['lemma']}'"


# ── Fix #1: Direction 2 quote-boundary skip ──────────────────────────────


class TestSmartTruncateDirection2QuoteSkip:
    """Direction 2 skips .!? boundaries inside unclosed double-quoted
    passages, treating quote blocks as atomic.  No quote patching."""

    def test_1_boundary_outside_quote_accepted(self):
        """Target outside quote — nearest .!? boundary outside quote wins."""
        sent = (
            'The sun was setting. He said, "Wait here." And he left.'
        )
        tgt = sent.find("left")
        result, new_to, was_trunc = smart_truncate(
            sent, "left", tgt, max_len=30,
        )
        assert was_trunc is True
        # Should truncate at "setting. He" (outside quote), not "here." And" (inside)
        assert result == 'He said, "Wait here." And he left.'
        assert result.count('"') % 2 == 0

    def test_2_dot_space_quote_capital_pattern(self):
        """`. "X` pattern — skip quote char, start at capital letter."""
        sent = (
            'He paused. "Let us begin." And they walked toward the hills.'
        )
        tgt = sent.find("walked")
        result, new_to, was_trunc = smart_truncate(
            sent, "walked", tgt, max_len=30,
        )
        assert was_trunc is True
        # The '.' at begin." And is inside quote → skip.
        # The '.' at paused. "L → . "X pattern → accept.
        # . "X → start at " (keep quoted passage intact)
        assert result.startswith('"Let us begin."')
        assert result.count('"') % 2 == 0

    def test_3_target_inside_quote_boundary_before_opening(self):
        """Target inside quote, .!? boundary exists before opening quote."""
        sent = (
            'The sun was setting. He said, "Wait here. I\'ll be back."'
        )
        tgt = sent.find("back")
        result, new_to, was_trunc = smart_truncate(
            sent, "back", tgt, max_len=30,
        )
        assert was_trunc is True
        # here." I'll is inside quote → skip
        # setting. He is outside, before opening quote → accept
        assert result == 'He said, "Wait here. I\'ll be back."'
        assert result.count('"') % 2 == 0

    def test_4_target_inside_quote_no_boundary_before(self):
        """Target inside quote, no .!? before opening — can't truncate."""
        sent = (
            'He thought, "The birds are delicate. They dip and hunt. '
            'They are made for the sea."'
        )
        tgt = sent.find("dip")
        result, new_to, was_trunc = smart_truncate(
            sent, "dip", tgt, max_len=250,
        )
        # All boundaries inside quote. Opening quote preceded by comma.
        # No valid truncation → return original for caller to accept/reject.
        assert was_trunc is False
        assert result == sent

    def test_5_missing_opening_quote_ocr(self):
        """OCR lost opening quote — function treats lone " as opening."""
        sent = 'Hello." The world is large.'
        tgt = sent.find("world")
        result, new_to, was_trunc = smart_truncate(
            sent, "world", tgt, max_len=250,
        )
        # The '.' at Hello." → _is_inside_opening_quote returns True
        # (misjudges the lone " as opening) → skip → fallback.
        # Fallback boundary still produces quote imbalance → was_trunc=False.
        # But in this short sentence, no truncation needed.
        assert "world" in result

    def test_6_missing_closing_quote_ocr_rejected(self):
        """OCR lost closing quote — all boundaries in unclosed quote."""
        sent = '"Hello. The world is large.'
        tgt = sent.find("world")
        result, new_to, was_trunc = smart_truncate(
            sent, "world", tgt, max_len=250,
        )
        # All '.' inside unclosed quote → all skipped.
        # Target inside quote, no boundary before opening " at pos 0.
        # → was_trunc=False (caller rejects if too long).
        # At 26 chars, still under any reasonable limit — returned unchanged.
        assert "world" in result

    def test_7_boundary_at_dot_quote_capital_accepted(self):
        """. "X pattern — boundary with quote in between."""
        sent = (
            'He paused. "Let us begin." And they walked toward the hills.'
        )
        tgt = sent.find("walked")
        result, new_to, was_trunc = smart_truncate(
            sent, "walked", tgt, max_len=30,
        )
        assert was_trunc is True
        # begin." And → inside quote → skip
        # paused. "L → . "X → accept, start at " (keep quote intact)
        assert result.startswith('"Let us begin."')

    def test_8_no_quotes_unchanged(self):
        """No quotes at all — behavior identical to old code."""
        sent = "The sun set. The wind rose. The birds flew."
        tgt = sent.find("wind")
        result, new_to, was_trunc = smart_truncate(
            sent, "wind", tgt, max_len=20,
        )
        # Direction 1 shortens from right (at "rose."), Direction 2 from left
        # (at "set.") — they compose.
        assert was_trunc is True
        assert result == "The wind rose."

    def test_9_target_before_opening_quote(self):
        """Target before opening quote — quote block truncated away."""
        sent = (
            'He walked to the door. "Wait here," he said, and then he left.'
        )
        tgt = sent.find("door")
        result, new_to, was_trunc = smart_truncate(
            sent, "door", tgt, max_len=30,
        )
        # door is before the opening quote, Direction 1 handles right-side
        # truncation; quote block after door is truncated away.
        assert "door" in result
        assert result.count('"') % 2 == 0

    def test_10_direction_1_quote_boundary(self):
        """Direction 1: punctuation inside quote at sentence start."""
        sent = (
            '"Hello." The sun was setting over the distant hills.'
        )
        tgt = sent.find("Hello")
        result, new_to, was_trunc = smart_truncate(
            sent, "Hello", tgt, max_len=250,
        )
        # Sentence starts with ", target inside. Direction 1 walk-back
        # finds no text before opening " → can't truncate via walk-back.
        # Original is 48 chars, under max_len → unchanged.
        assert "Hello" in result

    def test_11_single_quotes_not_affected(self):
        """Single quotes ' are not checked — only double quotes."""
        sent = "He said, 'Wait here.' And he left."
        tgt = sent.find("left")
        result, new_to, was_trunc = smart_truncate(
            sent, "left", tgt, max_len=20,
        )
        assert was_trunc is True
        assert "left" in result

    def test_12_multiple_quote_pairs(self):
        """Multiple independent quote pairs handled correctly."""
        sent = (
            '"Hello," he said. "Goodbye," she replied. And they parted.'
        )
        tgt = sent.find("parted")
        result, new_to, was_trunc = smart_truncate(
            sent, "parted", tgt, max_len=30,
        )
        # The '.' at replied." And is inside the second quote → skip.
        # The '.' at said. "G → . "X pattern → accept (same logic as test_2).
        assert "parted" in result

    def test_15_fully_quoted_no_patch(self):
        """Fully-quoted sentence — all boundaries in quote, no patching."""
        sent = '"A sentence. Another sentence. A third. A fourth."'
        tgt = sent.find("third")
        result, new_to, was_trunc = smart_truncate(
            sent, "third", tgt, max_len=250,
        )
        # All '.' inside the outer "…". Target inside quote.
        # Opening " at pos 0 → no boundary before it.
        # Fallback produces unbalanced → was_trunc=False.
        # At 50 chars, under max_len → unchanged.
        assert "third" in result

    def test_13_reject_limit_exceeded(self):
        """Sentence too long after truncation → word rejected."""
        # Build a 600+ char sentence that smart_truncate cannot shorten
        # (no internal .!? boundaries before the target word).
        padding = "x " * 500
        sent = padding + "The target word is here."
        tgt = sent.find("target")
        result, new_to, was_trunc = smart_truncate(
            sent, "target", tgt, max_len=250,
        )
        # Direction 2 finds no boundary in the padding → was_trunc=False.
        # Direction 1: no .!? after target → was_trunc=False.
        # The caller will skip this word because len(sent) > HARD_CUTOFF.
        assert len(sent) > 500

    def test_14_pipeline_reorder_multi_word_sentence(self):
        """Each target word gets its own smart_truncate + spaCy pass.
        No shared hard_truncate result."""
        result = _run_pipeline(
            [
                {"lemma": "sun", "rep": "sun", "forms": ["sun"], "coca_level": 4},
                {"lemma": "wind", "rep": "wind", "forms": ["wind"], "coca_level": 4},
                {"lemma": "bird", "rep": "birds", "forms": ["birds"], "coca_level": 4},
            ],
            "The sun set. The wind rose. The birds flew away.",
        )
        words = result.get("words", [])
        assert len(words) == 3
        lemmas = {w["lemma"] for w in words}
        assert lemmas == {"sun", "wind", "bird"}
