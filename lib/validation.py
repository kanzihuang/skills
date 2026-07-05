"""Pre-sync word entry validation.

Checks sentence length, <b> tag consistency, required fields, lemma
sanity, and punctuation artifacts.  Hard errors block sync; soft
warnings go to stderr.
"""

from __future__ import annotations

import re
import sys

from .config import MAX_SENTENCE_LENGTH
from .lemmatize import lemmatize
from .utils import lemmatize_word


def validate_word_entries(words: list[dict]) -> list[str]:
    """Validate word entries before sync. Returns list of error messages (empty = pass).

    Checks sentence length (<=MAX_SENTENCE_LENGTH), <b> tag matches word field,
    word actually appears in sentence text (after stripping tags),
    and required fields (ipa, definition_cn, translation_cn) are non-empty.

    Soft warnings (IPA format, definition sanity) are printed to stderr
    directly and do NOT block sync.
    """
    errors = []
    for w in words:
        word = w.get("word", "")
        sentence = w.get("sentence", "")

        # 1. <b> content must match word field (case-insensitive).
        b_match = re.search(r"<b>(.*?)</b>", sentence)
        b_text = b_match.group(1) if b_match else ""
        if b_text.lower() != word.lower():
            errors.append(f"[{word}] <b> mismatch: <b>{b_text}</b> != word '{word}'")

        # 1b. <b> must wrap the COMPLETE surface word
        if b_match and b_text:
            after = sentence[b_match.end():]
            if after and after[0].isalpha() and after[0].islower():
                remaining = ""
                for ch in after:
                    if ch.isalpha():
                        remaining += ch
                    else:
                        break
                full_word = b_text + remaining
                errors.append(
                    f"[{word}] <b> tag splits surface word: "
                    f"<b>{b_text}</b>{remaining} -> should wrap complete "
                    f"surface form '<b>{full_word}</b>'"
                )

        # 2. Sentence must contain the word (case-insensitive, after stripping tags)
        clean_sentence = re.sub(r"<[^>]+>", "", sentence)
        if word.lower() not in clean_sentence.lower():
            errors.append(
                f"[{word}] word not found in sentence: "
                f"'{word}' not in '{clean_sentence[:80]}{'...' if len(clean_sentence) > 80 else ''}'"
            )

        # 3. Sentence length check
        clean_len = len(re.sub(r"</?b>", "", sentence))
        if clean_len > MAX_SENTENCE_LENGTH:
            errors.append(
                f"[{word}] sentence too long: {clean_len} chars "
                f"(max {MAX_SENTENCE_LENGTH})"
            )

        # 4. Required fields non-empty (hard error)
        for field in ["ipa", "definition_cn", "translation_cn"]:
            if not w.get(field):
                errors.append(f"[{word}] missing '{field}'")

        # 4.5 lemma sanity
        json_lemma = w.get("lemma", "").strip()
        if json_lemma:
            wl = word.lower()
            if wl.endswith(("ed", "ing")):
                if json_lemma.lower() != wl:
                    errors.append(
                        f"[{word}] -ed/-ing word with lemma '{json_lemma}' "
                        f"that differs from surface form. "
                        f"See SHARED_WORKFLOW.md Step 2D-0 lemma ==: "
                        f"if adjective -> set lemma='{word}'; "
                        f"if regular inflection -> leave lemma empty."
                    )
            else:
                resolved = lemmatize(word)
                machine = lemmatize_word(word)
                if (json_lemma.lower() != wl
                        and json_lemma.lower() != machine.lower()
                        and len(json_lemma) > len(word)):
                    errors.append(
                        f"[{word}] suspicious lemma '{json_lemma}': differs from both "
                        f"surface form '{word}' and lemmatize_word() result '{machine}'. "
                        f"Leave lemma empty for regular inflection (auto-correct -> '{resolved}')"
                    )

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
