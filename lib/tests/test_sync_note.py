"""Test sync_anki — audio naming, WordId/bookId bridging,
incremental safety dedup matching, and audio failure blocking.

Key lessons from the 老人与海 case study:
  - Audio filenames must include bookId to prevent global media conflicts
    (e.g. "wound" pronounced differently in different books).
  - WordId = {safe_filename(surface_form)}_{bookId} — the bookId suffix
    is the only reliable Anki ↔ WeRead bridge; title matching is fragile.
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
# 2. WordId / bookId bridging — {safe_filename(surface_form)}_{bookId}
# ═══════════════════════════════════════════════════════════════════

class TestWordIdBookIdBridging:
    """WordId = {safe_filename(surface)}_{bookId} enables precise
    Anki ↔ WeRead matching. The bookId suffix is the reliable bridge;
    title matching is fragile and not used."""

    def test_word_id_includes_book_id(self):
        note = build_note_entry(make_word("test"), ipa="/tɛst/", book_id="12345")
        assert "test_12345" == note["fields"]["WordId"]

    def test_word_id_uses_surface_form_not_lemma(self):
        """WordId uses surface form for variant deduplication —
        different surface forms (asteroid/asteroids) get different WordIds."""
        note = build_note_entry(
            make_word("pondered"), ipa="/ˈpɑːndər/",
            book_id="22720170", lemma="ponder",
        )
        # WordId should use surface "pondered", not lemma "ponder"
        assert "pondered_22720170" == note["fields"]["WordId"]
        # But Word field should show the lemma
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
        """WordId applies safe_filename to handle non-alphanumeric characters."""
        note = build_note_entry(make_word(word), ipa="/tɛst/", book_id="12345")
        assert note["fields"]["WordId"] == f"{expected}_12345"


# ═══════════════════════════════════════════════════════════════════
# 3. Incremental safety — existing cards not modified
# ═══════════════════════════════════════════════════════════════════

class TestIncrementalSafety:
    """Sync mode only adds new cards, never modifies existing cards.
    This preserves review progress and scheduling data."""

    def test_dedup_id_matches_build_note_entry_word_id(self):
        """The WordId produced by build_note_entry must be predictable
        so that the sync dedup check (line 1203) correctly identifies
        cards already in the deck."""
        for word in ["test", "boa", "pondered", "disheartened"]:
            note = build_note_entry(
                make_word(word), ipa="/tɛst/", book_id="12345",
            )
            # The dedup check at sync time computes:
            expected_id = f"{word.strip().lower()}_12345"
            assert note["fields"]["WordId"] == expected_id, (
                f"WordId mismatch for {word}: "
                f"build_note_entry={note['fields']['WordId']} "
                f"vs dedup_check={expected_id}"
            )

    def test_lemma_change_does_not_affect_word_id(self):
        """Changing the lemma (e.g. fixing a mis-lemmatization) should not
        change the WordId — WordId is tied to the surface form, so existing
        cards can still be found for dedup."""
        note1 = build_note_entry(
            make_word("disheartened"), ipa="/dɪsˈhɑːrtən/",
            book_id="22720170", lemma="dishearten",
        )
        note2 = build_note_entry(
            make_word("disheartened"), ipa="/dɪsˈhɑːrtənd/",
            book_id="22720170", lemma="disheartened",
        )
        # WordId stable despite lemma change
        assert note1["fields"]["WordId"] == note2["fields"]["WordId"]

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
        are placed in skipped_words, not new_words."""
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
            dedup_id = f"{w['word'].strip().lower()}_{book_id}"
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

        word = "good-bye"
        book_id = "12345"

        # What build_note_entry produces
        note = build_note_entry(
            make_word(word), ipa="/tɛst/", book_id=book_id,
        )

        # The dedup check (line 1214) now uses safe_filename — must match
        dedup_id = f"{safe_filename(word.strip().lower())}_{book_id}"

        assert note["fields"]["WordId"] == dedup_id, (
            f"Mismatch: build_note_entry={note['fields']['WordId']} "
            f"vs dedup={dedup_id}"
        )


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
