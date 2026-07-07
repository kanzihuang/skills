"""Pre-sync word entry validation.

Checks sentence length, target word presence in sentence, required fields,
and lemma sanity.  Hard errors block sync; soft warnings go to stderr.

In the new design, sentences are stored WITHOUT <b> tags — the tag is
inserted by build_note_entry() using target_offset.  Validation checks
the word at target_offset instead of parsing <b> tags.
"""

from __future__ import annotations

import re
import sys

from .config import MAX_SENTENCE_LENGTH, MIN_SENTENCE_LENGTH
from .lemmatize import lemmatize
from .utils import lemmatize_word


def validate_word_entries(words: list[dict]) -> list[str]:
    """Validate word entries before sync. Returns list of error messages (empty = pass).

    Checks sentence length (MIN_SENTENCE_LENGTH ≤ len ≤ MAX_SENTENCE_LENGTH),
    target word at target_offset matches word field, and required fields
    (ipa, definition_cn, translation_cn) are non-empty.

    Soft warnings (IPA format, definition sanity, sentence too short) are
    printed to stderr directly and do NOT block sync.
    """
    errors = []
    for w in words:
        word = w.get("word", "")
        sentence = w.get("sentence", "")
        target_offset = w.get("target_offset", -1)

        # 1. Word at target_offset must match word field
        if target_offset >= 0 and target_offset + len(word) <= len(sentence):
            sent_word = sentence[target_offset:target_offset + len(word)]
            if sent_word.lower() != word.lower():
                errors.append(
                    f"[{word}] target_offset mismatch: "
                    f"'{sent_word}' at offset {target_offset} != word '{word}'"
                )
        elif target_offset >= 0:
            errors.append(
                f"[{word}] target_offset {target_offset} out of range "
                f"for sentence length {len(sentence)}"
            )

        # 2. Sentence must contain the word (case-insensitive)
        if word.lower() not in sentence.lower():
            errors.append(
                f"[{word}] word not found in sentence: "
                f"'{word}' not in '{sentence[:80]}{'...' if len(sentence) > 80 else ''}'"
            )

        # 3. Sentence length check
        clean_len = len(sentence)
        if clean_len > MAX_SENTENCE_LENGTH:
            errors.append(
                f"[{word}] sentence too long: {clean_len} chars "
                f"(max {MAX_SENTENCE_LENGTH})"
            )

        # 3b. Minimum sentence length check (soft warning)
        if clean_len < MIN_SENTENCE_LENGTH:
            print(
                f"  [WARN] [{word}] sentence too short: {clean_len} chars "
                f"(min {MIN_SENTENCE_LENGTH}) — may lack sufficient context",
                file=sys.stderr,
            )

        # 4. Required fields non-empty (hard error)
        for field in ["ipa", "definition_cn", "translation_cn"]:
            if not w.get(field):
                errors.append(f"[{word}] missing '{field}'")

        # --- Soft warnings (stderr only, do not block sync) ---

        # 5. IPA format sanity check
        ipa = w.get("ipa", "")

        # 6. IPA matches lemma (not surface form)
        json_lemma2 = w.get("lemma", "").strip()
        resolved = lemmatize(word, json_lemma=json_lemma2)
        if ipa and resolved != word.lower() and "/ɪŋ/" in ipa and not resolved.endswith("ing"):
            print(
                f"  [WARN] [{word}] IPA contains /ɪŋ/ but lemma '{resolved}' "
                f"does not end in -ing (surface form: '{word}')",
                file=sys.stderr,
            )
        if ipa:
            ipa_clean = ipa.strip()
            if "/" not in ipa_clean:
                print(f"  [WARN] [{word}] IPA missing '/' delimiters: {ipa}", file=sys.stderr)
            else:
                phonemes = re.sub(r"[/ˈˌ.]", "", ipa_clean)
                if len(phonemes) < 2:
                    print(f"  [WARN] [{word}] IPA too short: {ipa}", file=sys.stderr)
            if re.search(r"[一-鿿]", ipa_clean):
                print(f"  [WARN] [{word}] IPA contains Chinese characters: {ipa}", file=sys.stderr)

        # 6. Definition sanity check
        definition = w.get("definition_cn", "")
        if definition:
            cjk_count = len(re.findall(r"[一-鿿]", definition))
            if cjk_count < 2:
                print(f"  [WARN] [{word}] definition_cn has <2 Chinese chars: '{definition}'", file=sys.stderr)
            if definition.strip().lower() == word.lower():
                print(f"  [WARN] [{word}] definition_cn equals word: '{definition}'", file=sys.stderr)

        # 7. Sentence fragment detection (soft warnings)
        clean = re.sub(r"<[^>]+>", "", sentence).strip()
        if clean:
            first_char = clean[0]
            if first_char.isalpha() and first_char.islower():
                print(
                    f"  [WARN] [{word}] sentence starts with lowercase "
                    f"'{first_char}' - may be a truncated fragment",
                    file=sys.stderr,
                )

            has_finite_verb = bool(
                re.search(r'\b(?:is|are|was|were|am|has|have|had|do|does|did|'
                          r'will|would|can|could|shall|should|may|might|must)\b',
                          clean, re.IGNORECASE)
            )
            if not has_finite_verb:
                verb_ending = bool(re.search(r'\b\w+(?:ed|s)\b', clean))
                if not verb_ending:
                    print(
                        f"  [WARN] [{word}] sentence may lack a finite verb "
                        f"- possible noun phrase fragment: '{clean[:80]}{'...' if len(clean) > 80 else ''}'",
                        file=sys.stderr,
                    )

            # 7c. Ends with function word
            _FUNCTION_ENDINGS: set[str] = {
                "from", "with", "at", "for", "to", "of", "in", "on", "by",
                "about", "into", "onto", "upon", "within", "without", "through",
                "across", "along", "around", "before", "after", "between",
                "among", "during", "until", "against", "toward", "towards",
                "over", "under", "behind", "beside", "beneath",
                "and", "but", "or", "nor", "so", "yet", "because",
                "although", "though", "while", "when", "where",
                "since", "if", "unless", "until", "as",
                "had", "has", "was", "were", "could", "would", "should",
                "also", "even", "just", "still", "then", "now", "only",
                "quite", "rather", "almost", "very", "too", "already",
                "always", "never", "often", "here", "there", "again",
                "once", "soon", "ever", "indeed", "hardly", "merely",
                "nearly", "else",
            }
            last_word = re.split(r'\s+', clean.rstrip('"\'') + ' ')[-2].strip().lower()
            if last_word in _FUNCTION_ENDINGS:
                errors.append(
                    f"[{word}] sentence ends with function word "
                    f"'{last_word}' - likely truncated fragment"
                )

            # 7d. Punctuation artifact
            stripped = clean.rstrip()
            if re.search(r',[.)]$', stripped) or stripped.endswith(','):
                errors.append(
                    f"[{word}] sentence has punctuation artifact "
                    f"({stripped[-3:]}...) - source-text boundary debris"
                )

        # 8. Translation quality checks (soft warnings)
        translation = w.get("translation_cn", "")
        if translation and sentence:
            _CN_TRUNCATION_ENDINGS = frozenset({
                "然后", "但是", "而且", "所以", "不过", "于是",
                "因此", "然而", "并且", "以及", "还是", "或者",
                "接着", "随后", "之后", "以后", "以前",
            })
            cn_clean = translation.strip().rstrip("，。！？、；：…")
            cn_last = cn_clean[-2:] if len(cn_clean) >= 2 else cn_clean
            if cn_last in _CN_TRUNCATION_ENDINGS or (
                len(cn_clean) >= 3 and cn_clean[-3:] in _CN_TRUNCATION_ENDINGS
            ):
                print(
                    f"  [WARN] [{word}] Chinese translation ends with "
                    f"'{cn_last}' - may be truncated (sentence: {clean[:50]}...)",
                    file=sys.stderr,
                )

    return errors


# Backward-compatible alias
_validate_word_entries = validate_word_entries
