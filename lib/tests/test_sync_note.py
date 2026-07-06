"""Test sync_anki — audio naming, WordId/bookId bridging,
incremental safety dedup matching, and audio failure blocking.

Key lessons from the 老人与海 case study:
  - Audio filenames must include bookId to prevent global media conflicts
    (e.g. "wound" pronounced differently in different books).
  - WordId = {safe_filename(resolved_lemma)}_{bookId} — the bookId suffix
    is the only reliable Anki ↔ WeRead bridge; title matching is fragile.
    Using the resolved lemma (not surface form) ensures cross-book dedup
    consistency: "pondered" and "pondering" map to the same WordId.
  - Incremental safety: existing cards must NOT be modified — sync only
    adds new cards, preserving review progress and scheduling data.
  - Audio failure: retry (edge_tts_bytes has 3 attempts), then block
    the sync — do NOT silently skip.
"""

import re
from unittest.mock import patch

import pytest
from lib.sync_anki import build_note_entry, _process_one_word
from lib.utils import safe_filename


# ── Helpers ──

def make_word(word="test", sentence=None, **overrides):
    """Build a minimal word data dict for build_note_entry testing."""
    entry = {
        "word": word,
        "sentence": sentence or f"This is a <b>{word}</b> test sentence.",
        "ipa": "/tɛst/",
        "definition_cn": "测试",
        "translation_cn": "测试翻译。",
    }
    entry.update(overrides)
    return entry


# ═══════════════════════════════════════════════════════════════════
# 1. Audio filename format — {lemma}_{bookId}_word/sent.mp3
# ═══════════════════════════════════════════════════════════════════

class TestAudioFilenameFormat:
    """Audio filenames must include bookId to namespace audio globally."""

    def test_word_audio_includes_book_id(self):
        note = build_note_entry(make_word("test"), ipa="/tɛst/", book_id="12345")
        assert "[sound:test_12345_word.mp3]" == note["fields"]["WordAudio"]

    def test_sentence_audio_includes_book_id(self):
        note = build_note_entry(make_word("test"), ipa="/tɛst/", book_id="12345")
        assert "[sound:test_12345_sent.mp3]" == note["fields"]["SentenceAudio"]

    def test_audio_uses_lemma_when_provided(self):
        """When lemma differs from surface form, audio filenames use lemma."""
        note = build_note_entry(
            make_word("pondered"), ipa="/ˈpɑːndər/",
            book_id="22720170", lemma="ponder",
        )
        assert "[sound:ponder_22720170_word.mp3]" == note["fields"]["WordAudio"]
        assert "[sound:ponder_22720170_sent.mp3]" == note["fields"]["SentenceAudio"]

    def test_audio_falls_back_to_word_when_no_lemma(self):
        """When no lemma provided, audio filenames fall back to surface form."""
        note = build_note_entry(
            make_word("boa"), ipa="/ˈboʊʌ/", book_id="22720170",
        )
        assert "[sound:boa_22720170_word.mp3]" == note["fields"]["WordAudio"]

    def test_different_books_same_lemma_produce_different_filenames(self):
        """Same lemma across different books must not collide in media store."""
        note1 = build_note_entry(
            make_word("wound"), ipa="/wuːnd/", book_id="111",
            lemma="wound",
        )
        note2 = build_note_entry(
            make_word("wound"), ipa="/waʊnd/", book_id="222",
            lemma="wound",
        )
        assert note1["fields"]["WordAudio"] != note2["fields"]["WordAudio"]
        assert "111" in note1["fields"]["WordAudio"]
        assert "222" in note2["fields"]["WordAudio"]

    def test_safe_filename_applied_to_lemma(self):
        """Unsafe characters in lemma are sanitized in filenames."""
        note = build_note_entry(
            make_word("test"), ipa="/tɛst/", book_id="12345",
            lemma="good-bye",
        )
        # safe_filename replaces '-' with '_'
        assert "good_bye" in note["fields"]["WordAudio"]
        assert "good-bye" not in note["fields"]["WordAudio"]


# ═══════════════════════════════════════════════════════════════════
# 2. WordId / bookId bridging — {safe_filename(resolved_lemma)}_{bookId}
# ═══════════════════════════════════════════════════════════════════

class TestWordIdBookIdBridging:
    """WordId = {safe_filename(resolved_lemma)}_{bookId} enables precise
    Anki ↔ WeRead matching and cross-book dedup. The bookId suffix is the
    reliable bridge; title matching is fragile and not used."""

    def test_word_id_includes_book_id(self):
        note = build_note_entry(make_word("test"), ipa="/tɛst/", book_id="12345")
        assert "test_12345" == note["fields"]["WordId"]

    def test_word_id_uses_lemma_not_surface_form(self):
        """WordId uses the resolved lemma for cross-book dedup consistency —
        "pondered" with lemma="ponder" gets WordId "ponder_22720170"."""
        note = build_note_entry(
            make_word("pondered"), ipa="/ˈpɑːndər/",
            book_id="22720170", lemma="ponder",
        )
        # WordId should use lemma "ponder", not surface "pondered"
        assert "ponder_22720170" == note["fields"]["WordId"]
        # Word field should also show the lemma
        assert "ponder" == note["fields"]["Word"]

    def test_word_id_lowercases_surface_form(self):
        """WordId is always lowercase for reliable dedup matching."""
        note = build_note_entry(
            make_word("BOA"), ipa="/ˈboʊʌ/", book_id="22720170",
        )
        assert "boa_22720170" == note["fields"]["WordId"]

    def test_same_word_different_books_different_word_ids(self):
        """The same word in different books gets distinct WordIds —
        bookId is the namespace, preventing cross-book card mixing."""
        note1 = build_note_entry(make_word("fair"), ipa="/fer/", book_id="111")
        note2 = build_note_entry(make_word("fair"), ipa="/fer/", book_id="222")
        assert "111" in note1["fields"]["WordId"]
        assert "222" in note2["fields"]["WordId"]
        assert note1["fields"]["WordId"] != note2["fields"]["WordId"]

    @pytest.mark.parametrize("word,expected", [
        ("test", "test"),
        ("good-bye", "good_bye"),       # hyphen → underscore
        ("it's", "it_s"),               # apostrophe → underscore
    ])
    def test_word_id_safe_filenames_special_chars(self, word, expected):
        """WordId applies safe_filename to handle non-alphanumeric characters.
        Explicit lemma prevents resolve_lemma from reducing the surface form."""
        note = build_note_entry(
            make_word(word), ipa="/tɛst/", book_id="12345",
            lemma=word,  # pass surface form as lemma to prevent auto-reduction
        )
        assert note["fields"]["WordId"] == f"{expected}_12345"


# ═══════════════════════════════════════════════════════════════════
# 3. Incremental safety — existing cards not modified
# ═══════════════════════════════════════════════════════════════════

class TestIncrementalSafety:
    """Sync mode only adds new cards, never modifies existing cards.
    This preserves review progress and scheduling data."""

    def test_dedup_id_matches_build_note_entry_word_id(self):
        """The WordId produced by build_note_entry must match what
        _make_word_id computes for the dedup check (single source of truth)."""
        from lib.sync_anki import _make_word_id

        for word in ["test", "boa", "pondered", "disheartened"]:
            wd = make_word(word)
            note = build_note_entry(wd, ipa="/tɛst/", book_id="12345")
            expected_id = _make_word_id(wd, "12345")
            assert note["fields"]["WordId"] == expected_id, (
                f"WordId mismatch for {word}: "
                f"build_note_entry={note['fields']['WordId']} "
                f"vs _make_word_id={expected_id}"
            )

    def test_lemma_change_does_affect_word_id(self):
        """Changing the lemma (e.g. fixing a mis-lemmatization) changes
        the WordId — WordId is tied to the resolved lemma for dedup consistency."""
        note1 = build_note_entry(
            make_word("disheartened"), ipa="/dɪsˈhɑːrtən/",
            book_id="22720170", lemma="dishearten",
        )
        note2 = build_note_entry(
            make_word("disheartened"), ipa="/dɪsˈhɑːrtənd/",
            book_id="22720170", lemma="disheartened",
        )
        # WordId reflects the lemma — different lemmas = different WordIds
        assert note1["fields"]["WordId"] == "dishearten_22720170"
        assert note2["fields"]["WordId"] == "disheartened_22720170"

    def test_explicit_lemma_in_word_id(self):
        """When Claude sets lemma explicitly (adj override), WordId uses it."""
        note = build_note_entry(
            make_word("blundering"), ipa="/ˈblʌndərɪŋ/",
            book_id="12345", lemma="blundering",
        )
        assert "blundering_12345" == note["fields"]["WordId"]
        assert "blundering" == note["fields"]["Word"]

    def test_word_id_ignores_sentence_changes(self):
        """Changing the sentence (e.g. selecting a better candidate) should
        not change the WordId — the card is still for the same word."""
        note1 = build_note_entry(
            make_word("boa", sentence="A <b>boa</b> constrictor."),
            ipa="/ˈboʊʌ/", book_id="22720170",
        )
        note2 = build_note_entry(
            make_word("boa", sentence="It was a picture of a <b>boa</b>."),
            ipa="/ˈboʊʌ/", book_id="22720170",
        )
        assert note1["fields"]["WordId"] == note2["fields"]["WordId"]

    def test_existing_word_ids_are_skipped(self):
        """Simulate the dedup logic: words whose WordId is already in the deck
        are placed in skipped_words, not new_words.  Uses _make_word_id."""
        from lib.sync_anki import _make_word_id

        words_data = [
            make_word("boa"),
            make_word("consequence"),
            make_word("devote"),
        ]
        book_id = "22720170"

        # Simulate: "boa" and "consequence" already exist in deck
        existing_ids = {"boa_22720170", "consequence_22720170"}

        new_words = []
        skipped_words = []
        for w in words_data:
            dedup_id = _make_word_id(w, book_id)
            if dedup_id in existing_ids:
                skipped_words.append(w)
            else:
                new_words.append(w)

        assert len(new_words) == 1
        assert new_words[0]["word"] == "devote"
        assert len(skipped_words) == 2
        assert {w["word"] for w in skipped_words} == {"boa", "consequence"}

    def test_dedup_uses_safe_filename_for_special_chars(self):
        """Dedup check must apply safe_filename to match build_note_entry WordId."""
        from lib.sync_anki import _make_word_id

        word = "good-bye"
        book_id = "12345"
        wd = make_word(word)

        # What build_note_entry produces
        note = build_note_entry(wd, ipa="/tɛst/", book_id=book_id)

        # _make_word_id computes the same thing (single source of truth)
        dedup_id = _make_word_id(wd, book_id)

        assert note["fields"]["WordId"] == dedup_id, (
            f"Mismatch: build_note_entry={note['fields']['WordId']} "
            f"vs _make_word_id={dedup_id}"
        )


# ═══════════════════════════════════════════════════════════════════
# 5. Intra-batch dedup — same lemma in one batch → first wins
# ═══════════════════════════════════════════════════════════════════

class TestIntraBatchDedup:
    """Words that lemmatize to the same root within a single batch must be
    deduplicated — only the first occurrence gets a card, subsequent ones
    are skipped.  This prevents:
      - audio filename collision (both words generate the same
        {lemma}_{suffix}_sent.mp3 → second overwrites first)
      - sentence field overwrite on the Anki card
    """

    def test_boa_and_boas_same_batch(self):
        """'boa' and 'boas' both lemmatize to 'boa' — second is skipped."""
        from lib.sync_anki import _make_word_id, lemmatize

        suffix = "060c532a71e0"
        words_data = [
            make_word("boa", sentence="It was a picture of a <b>boa</b>."),
            make_word("boas", sentence="I drew <b>boas</b> from the outside."),
        ]

        # Simulate the intra-batch dedup added in add_new_cards()
        seen: set[str] = set()
        new_words = []
        skipped_words = []
        for w in words_data:
            wid = _make_word_id(w, suffix)
            if wid in seen:
                skipped_words.append(w)
                continue
            seen.add(wid)
            # (existing Anki dedup would go here — not relevant for this test)
            new_words.append(w)

        assert len(new_words) == 1, (
            f"Expected 1 new word, got {len(new_words)}: "
            f"{[w['word'] for w in new_words]}"
        )
        assert new_words[0]["word"] == "boa", "First occurrence should win"
        assert len(skipped_words) == 1
        assert skipped_words[0]["word"] == "boas"

    def test_pondered_and_pondering_same_batch(self):
        """'pondered' and 'pondering' both lemmatize to 'ponder'."""
        from lib.sync_anki import _make_word_id

        suffix = "abc123"
        words_data = [
            make_word("pondered", sentence="I <b>pondered</b> deeply."),
            make_word("pondering", sentence="I was <b>pondering</b>."),
        ]

        seen: set[str] = set()
        new_words = []
        skipped_words = []
        for w in words_data:
            wid = _make_word_id(w, suffix)
            if wid in seen:
                skipped_words.append(w)
                continue
            seen.add(wid)
            new_words.append(w)

        assert len(new_words) == 1
        assert new_words[0]["word"] == "pondered"
        assert len(skipped_words) == 1
        assert skipped_words[0]["word"] == "pondering"

    def test_explicit_lemma_blocks_intra_dedup(self):
        """Explicit lemma='astounded' vs auto-lemmatize 'astound' — different IDs."""
        from lib.sync_anki import _make_word_id

        suffix = "abc123"
        # With explicit lemma 'astounded' → WordId = astounded_abc123
        w1 = make_word("astounded", lemma="astounded")
        # No explicit lemma, lemmatizes to 'astound' → WordId = astound_abc123
        w2 = make_word("astounded")  # auto-lemmatize to "astound"

        w1_id = _make_word_id(w1, suffix)
        w2_id = _make_word_id(w2, suffix)

        # They SHOULD be different: adjective vs verb lemmatization
        seen: set[str] = set()
        new_words = []
        for w in [w1, w2]:
            wid = _make_word_id(w, suffix)
            if wid in seen:
                continue
            seen.add(wid)
            new_words.append(w)

        assert len(new_words) == 2, (
            f"Explicit lemma creates different WordIds: {w1_id} vs {w2_id}"
        )

    def test_three_words_same_lemma(self):
        """Three surface forms → same lemma → only first card created."""
        from lib.sync_anki import _make_word_id

        suffix = "test123"
        words_data = [
            make_word("blink", sentence="I <b>blink</b>."),
            make_word("blinked", sentence="I <b>blinked</b>."),
            make_word("blinking", sentence="I was <b>blinking</b>."),
        ]

        seen: set[str] = set()
        new_words = []
        skipped_words = []
        for w in words_data:
            wid = _make_word_id(w, suffix)
            if wid in seen:
                skipped_words.append(w)
                continue
            seen.add(wid)
            new_words.append(w)

        assert len(new_words) == 1
        assert new_words[0]["word"] == "blink"
        assert len(skipped_words) == 2
        assert {w["word"] for w in skipped_words} == {"blinked", "blinking"}


# ═══════════════════════════════════════════════════════════════════
# 4. Audio failure → retry → block (not silently skip)
# ═══════════════════════════════════════════════════════════════════

class TestAudioFailureBlocks:
    """When Edge TTS fails after all retries, _process_one_word must raise
    RuntimeError — not silently skip the audio. The retry happens inside
    edge_tts_bytes (3 attempts, 0.75s delay), and the sync flow blocks
    on any failed word."""

    def test_word_audio_failure_raises(self):
        """When edge_tts_bytes returns None for word audio, RuntimeError is raised."""
        w = make_word("test", ipa="/tɛst/")

        with patch("lib.sync_anki.edge_tts_bytes", return_value=None):
            with pytest.raises(RuntimeError, match="Word audio generation failed"):
                _process_one_word(w, "12345", no_audio=False)

    def test_sentence_audio_failure_raises(self):
        """When edge_tts_bytes returns None for sentence audio, RuntimeError is raised."""
        w = make_word("test", ipa="/tɛst/")
        word_audio_bytes = [b"fake audio"]  # always succeed
        sentence_audio_bytes = [None]  # fail

        def fake_edge_tts_bytes(text, ipa=None):
            if ipa:
                return word_audio_bytes.pop(0)
            return sentence_audio_bytes.pop(0)

        with patch("lib.sync_anki.edge_tts_bytes", side_effect=fake_edge_tts_bytes):
            with pytest.raises(RuntimeError, match="Sentence audio generation failed"):
                _process_one_word(w, "12345", no_audio=False)

    def test_both_audio_fail_word_audio_raised_first(self):
        """When both fail, word audio error is raised (checked first)."""
        w = make_word("test", ipa="/tɛst/")

        with patch("lib.sync_anki.edge_tts_bytes", return_value=None):
            with pytest.raises(RuntimeError, match="Word audio generation failed"):
                _process_one_word(w, "12345", no_audio=False)

    def test_no_audio_flag_skips_generation(self):
        """With no_audio=True, audio generation is skipped entirely — no error."""
        w = make_word("test", ipa="/tɛst/")  # has IPA but no_audio=True
        note, audio_uploads, ipa = _process_one_word(w, "12345", no_audio=True)
        assert len(audio_uploads) == 0
        assert note["fields"]["WordId"] == "test_12345"

    def test_no_ipa_skips_word_audio_but_not_sentence(self):
        """Without IPA, word audio is skipped but sentence audio must succeed."""
        w = make_word("test")
        w["ipa"] = ""  # no IPA

        # Must also mock _cmu_ipa — "test" is in cmudict so the code would
        # fill in IPA from cmudict, defeating the "no IPA" test condition.
        with patch("lib.sync_anki._cmu_ipa", return_value=""):
            with patch("lib.sync_anki.edge_tts_bytes", return_value=b"fake sent audio"):
                note, audio_uploads, ipa = _process_one_word(w, "12345", no_audio=False)
                assert len(audio_uploads) == 1  # only sentence audio
                assert audio_uploads[0][0].endswith("_sent.mp3")

    def test_no_ipa_sentence_audio_failure_still_raises(self):
        """Even without word audio (no IPA), sentence audio failure must block."""
        w = make_word("test")
        w["ipa"] = ""

        with patch("lib.sync_anki._cmu_ipa", return_value=""):
            with patch("lib.sync_anki.edge_tts_bytes", return_value=None):
                with pytest.raises(RuntimeError, match="Sentence audio generation failed"):
                    _process_one_word(w, "12345", no_audio=False)
