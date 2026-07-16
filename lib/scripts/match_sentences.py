#!/usr/bin/env python3
"""Step 2A: Mechanical sentence matching + POS-aware lemmatization.

Reads filter_fulltext.py JSON output and source text, splits text into
sentences once, and makes a single pass: each sentence is run through
spaCy once; matched entries update their (lemma, pos) best sentence
incrementally.  No candidate accumulation — only the best entry per
(lemma, pos) group is retained.

Output sentences are stored WITHOUT <b> tags — sync_anki.py adds <b> tags
when building Anki cards.

No semantic truncation — that is handled by Step 2B (Claude).  Only a hard
500-char cutoff guards against extreme outliers.
"""

import argparse
import json
import os
import re
import sys

import pysbd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib.chapter_detect import detect_story_start
from lib.coca import in_coca
from lib.config import HARD_CUTOFF, MIN_SENTENCE_LENGTH, MAX_SENTENCE_LENGTH, SENTENCE_END_FUNCTION_WORDS
from lib.utils import build_sentence_regex, normalize_quotes


def _get_segmenter() -> pysbd.Segmenter:
    """Return a cached PySBD segmenter (lazy init)."""
    return pysbd.Segmenter(language="en", clean=True)


_DIALOGUE_ATTRIBUTION_RE = re.compile(r'([:,])[ \t]*\n{2,}[ \t]*["“”]')



def _normalize_dialogue_attribution(text: str) -> str:
    """Join colon/comma-ending attribution lines with their dialogue.

    In some plain-text editions, dialogue-attribution lines are separated
    from their spoken text by blank lines:

        He looked attentively, then:

        "No! That one is already very ill."

        He replied,

        "It does not matter. Draw me a sheep."

    PySBD splits these at the blank line, producing fragment sentences
    like 'He looked attentively, then:' or 'He replied,'.  Collapse the
    whitespace so PySBD sees the attribution and dialogue as one sentence.
    """
    return _DIALOGUE_ATTRIBUTION_RE.sub(r'\1 "', text)


def split_sentences(text: str, source_text: str | None = None) -> list[str]:
    """Split text into sentences using PySBD.

    If *source_text* is provided, adjacent fragment sentences (split by
    blank lines in the source) are merged and verified as continuous
    substrings of *source_text*.
    """
    text = _normalize_dialogue_attribution(text)
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    seg = _get_segmenter()
    sentences = seg.segment(text)
    sentences = [_clean_quote_artifact(s.strip()) for s in sentences]
    sentences = [s for s in sentences if s]
    if source_text is not None:
        sentences = _merge_adjacent_fragments(sentences, source_text)
    return sentences


def _form_found_in_text(form: str, text: str) -> bool:
    """Check if *form* appears as a standalone word in *text*.

    Underscores are replaced with spaces before checking because plain-text
    files often use ``_word_`` for italics (e.g. ``_Jota_`` in Gutenberg texts).
    Without this, ``_`` (a ``\\w`` character) blocks the ``\\b`` word boundary.
    """
    cleaned = text.replace('_', ' ')
    return bool(re.search(r'\b' + re.escape(form) + r'\b', cleaned, re.IGNORECASE))


def _strip_non_alpha(text: str) -> str:
    """Strip all non-letter characters for source-text verification."""
    return re.sub(r'[^a-zA-Z]', '', text.lower())


def _clean_quote_artifact(sentence: str) -> str:
    """Remove PySBD dangling-quote artifacts from dialogue splitting."""
    return re.sub(r'^\"\s+\"', '"', sentence)


_QUOTES = '"' + '“' + '”' + "'" + '‘' + '’'


def _is_fragment(sentence: str) -> bool:
    """Return True if sentence appears to be an incomplete fragment.

    Signals (any one hit → potential fragment):
      1. Doesn't end with . ! ? after stripping trailing quotes
      2. Odd number of ASCII \" (unclosed quote)
      3. Starts with lowercase letter
    """
    s = sentence.strip()
    if not s:
        return True
    # Signal 3: starts lowercase
    if s[0].islower():
        return True
    # Signal 2: odd number of ASCII double quotes
    if s.count('"') % 2 != 0:
        return True
    # Signal 1: no sentence-ending punctuation after stripping quotes
    stripped = s.rstrip().rstrip(_QUOTES)
    if stripped and stripped[-1] not in ('.', '!', '?'):
        return True
    return False


def _fragment_starts_lowercase(sentence: str) -> bool:
    """Return True if *sentence* starts with lowercase, or quote+lowercase.

    Quote characters are not lowercase themselves, so the bare
    ``islower()`` check fails for fragments like
    ``"that man would be scorned..."`` which start with a quote.
    Check the first non-quote character instead.
    """
    s = sentence.strip()
    if not s:
        return False
    if s[0].islower():
        return True
    if s[0] in _QUOTES and len(s) > 1 and s[1].islower():
        return True
    return False


def _merge_adjacent_fragments(
    sentences: list[str], source_text: str,
) -> list[str]:
    """Merge adjacent fragment sentences split by blank lines in the source.

    PySBD treats ``\\n\\n`` as a sentence boundary.  When the original text
    has blank lines *within* a sentence (OCR / formatting artifact), the
    result is fragments.  ``_normalize_dialogue_attribution()`` already
    handles ``[:,]\\n\\n\"`` dialogue patterns — this function catches the
    remaining cases.

    Fragment signals (odd quotes, lowercase start, missing terminal
    punctuation) indicate that a sentence is incomplete but do not reliably
    indicate *which direction* is broken.  Therefore no direction inference
    is performed — both forward and backward merges are attempted for every
    fragment.  ``build_sentence_regex()`` verification against *source_text*
    is the sole safety check.

    Only a single pass is performed — merged results are not re-processed
    for further merges.  This prevents cascading while still handling the
    common single-hop fragment patterns.

    Returns a new list with merges applied.
    """
    if len(sentences) < 2:
        return list(sentences)

    result = list(sentences)
    merged = []
    i = 0
    while i < len(result):
        s = result[i]
        odd_quotes = s.count('"') % 2 != 0

        # Backward merge first: fragment + previous sentence in *merged*.
        # Both must be fragments.  Tried before forward merge so that a
        # lowercase-start fragment joins the preceding fragment that was
        # just forward-merged in the previous step (e.g. "cough"+"most"
        # then "dreadfully" backward-merged into "cough most").
        if (
            _is_fragment(s)
            and merged
            and _is_fragment(merged[-1])
        ):
            candidate = merged[-1] + " " + s
            if re.search(build_sentence_regex(candidate), source_text):
                merged[-1] = candidate
                i += 1
                continue

        # Forward merge: fragment + next sentence.
        # Triggers: (a) next starts lowercase, or (b) fragment has odd
        #   quotes (unclosed quote whose closing quote may be in the next
        #   sentence even if it starts uppercase).
        if (
            _is_fragment(s)
            and i + 1 < len(result)
            and result[i + 1].strip()
        ):
            next_lower = _fragment_starts_lowercase(result[i + 1])
            if next_lower or odd_quotes:
                candidate = s + " " + result[i + 1]
                if re.search(build_sentence_regex(candidate), source_text):
                    merged.append(candidate)
                    i += 2
                    continue

        merged.append(s)
        i += 1
    return merged


def _is_inside_opening_quote(text: str, pos: int) -> bool:
    """Return True if *pos* is inside an unclosed double-quoted passage.

    Finds the last ``"`` at or before *pos* and counts how many ``"``
    precede it.  An even count means that ``"`` is an OPENING quote whose
    matching close is still missing — so *pos* is inside an unclosed quote.

    Returns False when no ``"`` is found at or before *pos*.
    """
    last_quote = text.rfind('"', 0, pos + 1)
    if last_quote < 0:
        return False
    quotes_before = text[:last_quote].count('"')
    return quotes_before % 2 == 0  # even → opening


def _cleanup_unclosed_quote(
    result: str, target_word: str, target_offset: int,
    tail: str | None = None,
) -> tuple[str, int]:
    """Remove unclosed opening quote and preceding text after truncation.

    When truncation cuts a sentence inside a quoted passage, the result may
    have an odd number of ``"`` characters — the last one is an opening quote
    whose matching close was truncated away.  Remove that quote and the text
    before it (typically a prior, balanced quoted passage), keeping only the
    clean text after it — as long as *target_word* is preserved.

    If *tail* (text from the original sentence after the truncation point)
    is provided, a forward search for the missing closing ``"`` is attempted
    first — extending the truncated result to include it.  This preserves
    the original dialogue structure instead of stripping the attribution.

    Returns ``(cleaned_text, new_target_offset)``.
    """
    if result.count('"') % 2 == 0:
        return result, target_offset  # balanced — nothing to do

    last_quote = result.rfind('"')
    # The raw text after the last quote (may have leading spaces).
    after_raw = result[last_quote + 1:]
    after_quote = after_raw.lstrip()
    if not after_quote:
        return result, target_offset

    # Compute how many characters were removed from the front.
    stripped_spaces = len(after_raw) - len(after_quote)
    chars_removed = last_quote + 1 + stripped_spaces
    new_tgt = target_offset - chars_removed

    if (new_tgt >= 0
            and new_tgt + len(target_word) <= len(after_quote)
            and after_quote[new_tgt:new_tgt + len(target_word)].lower()
            == target_word.lower()):
        # Stripping everything before the unclosed " would produce a
        # lowercase-start sentence.  Try forward search first: find the
        # missing closing " in *tail* and extend the result to include it.
        if tail and after_quote and after_quote[0].islower():
            closing = tail.find('"')
            if closing >= 0:
                extended = result + tail[:closing + 1]
                ext_tgt = target_offset
                if (ext_tgt >= 0
                        and ext_tgt + len(target_word) <= len(extended)
                        and extended[ext_tgt:ext_tgt + len(target_word)].lower()
                        == target_word.lower()):
                    # Verify balanced quotes after extension
                    if extended.count('"') % 2 == 0:
                        return extended, ext_tgt
        # Forward search failed — fall through to original behaviour:
        # strip the text before the unclosed quote.
        return after_quote, new_tgt

    # Target word is BEFORE the last unclosed quote — the unclosed quote
    # and trailing text are an incomplete dialogue fragment that was cut
    # by truncation.  Strip from the last " onward.
    before_last_quote = result[:last_quote].rstrip()
    if before_last_quote:
        new_tgt = target_offset
        if (new_tgt >= 0
                and new_tgt + len(target_word) <= len(before_last_quote)
                and before_last_quote[new_tgt:new_tgt + len(target_word)].lower()
                == target_word.lower()):
            # Guard: stripping quoted speech must not produce a
            # sentence fragment.  If the remaining text has no terminal
            # punctuation, the truncation is invalid — keep the original
            # sentence so it can be reviewed in Step 2B rather than
            # silently reduced to a fragment.
            #
            # Exception: dialogue-attribution comma ("…and he thought,"
            # followed by the opening ").  Strip the comma — the clause
            # is grammatically complete without it.
            if before_last_quote[-1] == ',':
                # The character at last_quote is '"' by construction
                # (last_quote = result.rfind('"')).  A comma immediately
                # before an opening quote is a dialogue-attribution
                # pattern — the clause is grammatically complete.
                # Replace the comma with a period.
                return before_last_quote[:-1].rstrip() + '.', new_tgt
            if before_last_quote[-1] not in '.!?':
                return result, target_offset
            return before_last_quote, new_tgt

    return result, target_offset  # target word would be lost — keep original


def _walk_back_pre_quote_ok(pre_quote: str, sentence: str,
                            quote_pos: int) -> bool:
    """Check whether *pre_quote* (text before an opening ``"``) is an
    acceptable walk-back truncation point.

    Accepts text ending with terminal punctuation (``. ! ?``, except
    bare ``,``), and also text ending with ``,`` when the comma is
    immediately before the opening ``"`` — a dialogue-attribution
    pattern like ``…and he thought, "The birds…"``.  In the latter case
    *pre_quote* is modified in place (trailing comma stripped).
    """
    if not pre_quote:
        return False
    last = pre_quote[-1]
    if last in ('.', '!', '?'):
        if pre_quote.rstrip().endswith(','):
            return False  # "text,." is OCR debris
        return True
    # Dialogue-attribution comma: "…and he thought," + space + "
    if last == ',' and quote_pos < len(sentence) and sentence[quote_pos] == '"':
        # Strip the trailing comma — the clause is grammatically
        # complete without it (e.g. "…and he thought.").
        return True
    return False


def _strip_dialogue_attribution_comma(text: str, sentence: str,
                                      quote_pos: int) -> str:
    """Strip trailing ``,`` from *text* when it is a dialogue-attribution
    comma (followed by ``"`` in *sentence* at *quote_pos*).  The comma is
    replaced with a period — the clause before a dialogue quote is
    grammatically complete and needs terminal punctuation when the
    quoted speech is removed.

    Returns the (possibly modified) text.
    """
    if (text and text[-1] == ','
            and quote_pos < len(sentence)
            and sentence[quote_pos] == '"'):
        return text[:-1].rstrip() + '.'
    return text


def smart_truncate(
    sentence: str,
    target_word: str,
    target_offset: int,
    max_len: int = MAX_SENTENCE_LENGTH,
) -> tuple[str, int, bool]:
    """Truncate *sentence*, preserving *target_word*.

    Two directions, both scanning for sentence-ending punctuation (``.!?``):

    **Direction 1 — end-truncation.**  Scan right from *target_end* for
    the first ``.!?`` that actually shortens the sentence.  Same quote
    handling as before (dialogue boundaries, opening-quote walk-back).

    **Direction 2 — beginning-truncation.**  Scan left from *target_offset*
    for ``.!?`` + space + capital letter.  Pick the nearest such boundary
    (most target-relevant context).  *target_offset* is recalculated.

    Returns ``(new_sentence, target_offset, was_truncated)``.
    If no truncation point is found the ORIGINAL sentence is returned
    with ``was_truncated=False``.
    """
    if len(sentence) <= max_len:
        # Only return immediately if the sentence already ends with proper
        # sentence-ending punctuation.  Sentences under max_len that end
        # mid-thought (without .!?) — fall through to Direction 1 /
        # Direction 2 to find a genuine sentence boundary.
        stripped = sentence.rstrip()
        if stripped and stripped[-1] in '.!?':
            return sentence, target_offset, False
        # Closing quote after sentence-ending punctuation is also valid
        if (stripped and len(stripped) > 1
                and stripped[-1] in '"\'' and stripped[-2] in '.!?'):
            return sentence, target_offset, False

    target_end = target_offset + len(target_word)

    # ── Direction 1 & 2: scan right then left for .!? boundaries ───────
    # Direction 1 shortens from the right (after target).  Direction 2
    # shortens from the left (before target).  They compose: when Direction 1
    # cannot shorten enough alone, the result is fed into Direction 2 for
    # additional left-side truncation.

    # State variables for Direction 1 result (not returned immediately —
    # checked against max_len first).
    d1_sentence: str | None = None
    d1_tgt: int = -1

    for i in range(target_end, len(sentence)):
        ch = sentence[i]
        if ch in ('.', '!', '?'):
            if not _is_inside_opening_quote(sentence, i):
                cut_pos = i + 1
                if cut_pos < len(sentence):  # actually shortens
                    result = sentence[:cut_pos].rstrip()
                    # Back up past trailing function word
                    last_word = result.split()[-1].strip().lower().rstrip(':;,')
                    while last_word in SENTENCE_END_FUNCTION_WORDS:
                        result = result.rsplit(' ', 1)[0].rstrip()
                        if not result or len(result) <= target_end:
                            break
                        last_word = result.split()[-1].strip().lower().rstrip(':;,')
                    else:
                        if len(result) <= target_end:
                            break  # backed up past target — abandon
                        result, tgt = _cleanup_unclosed_quote(
                            result, target_word, target_offset,
                            tail=sentence[cut_pos:])
                        if len(result) <= max_len and not _is_fragment(result):
                            return result, tgt, True
                        # Result still too long — save for Direction 2
                        d1_sentence = result
                        d1_tgt = tgt
                break  # can't shorten further — fall through to direction 2
            # Punctuation inside an unclosed quote:
            # accept if followed by space + capital (dialogue boundary)
            if i + 1 < len(sentence):
                nxt = sentence[i + 1]
                accepted = False
                if nxt == ' ' and i + 2 < len(sentence) and sentence[i + 2].isupper():
                    accepted = True  # ". X"
                elif nxt.isupper():
                    accepted = True  # ".X"
                elif nxt == '"' and i + 2 < len(sentence):
                    nxt2 = sentence[i + 2]
                    if (nxt2 == ' ' and i + 3 < len(sentence)
                            and sentence[i + 3].isupper()):
                        accepted = True  # "." X"
                    elif nxt2.isupper():
                        accepted = True  # "."X"
                if accepted and i + 1 < len(sentence):
                    result = sentence[:i + 1].rstrip()
                    result, tgt = _cleanup_unclosed_quote(
                        result, target_word, target_offset,
                        tail=sentence[i + 1:])
                    if len(result) <= max_len and not _is_fragment(result):
                        return result, tgt, True
                    d1_sentence = result
                    d1_tgt = tgt
            # Inside opening quote without dialogue boundary —
            # walk back to before the opening quote.
            quote_pos = sentence.rfind('"', 0, i + 1)
            if quote_pos >= 0:
                pre_quote = sentence[:quote_pos].rstrip()
                if _walk_back_pre_quote_ok(pre_quote, sentence, quote_pos):
                    # Strip dialogue-attribution comma if present
                    pre_quote = _strip_dialogue_attribution_comma(
                        pre_quote, sentence, quote_pos)
                    last_w = pre_quote.split()[-1].strip().rstrip(';:')
                    if last_w.lower() not in SENTENCE_END_FUNCTION_WORDS:
                        result = pre_quote
                        if len(result) > target_end:
                            result, tgt = _cleanup_unclosed_quote(
                                result, target_word, target_offset)
                            if len(result) <= max_len and not _is_fragment(result):
                                return result, tgt, True
                            d1_sentence = result
                            d1_tgt = tgt
            # Continue scanning — this punctuation didn't work out
        elif ch == '"':
            if _is_inside_opening_quote(sentence, i):
                # Inside an opening quote — same walk-back logic as above
                quote_pos = sentence.rfind('"', 0, i + 1)
                if quote_pos >= 0:
                    pre_quote = sentence[:quote_pos].rstrip()
                    if _walk_back_pre_quote_ok(pre_quote, sentence, quote_pos):
                        # Strip dialogue-attribution comma if present
                        pre_quote = _strip_dialogue_attribution_comma(
                            pre_quote, sentence, quote_pos)
                        last_w = pre_quote.split()[-1].strip().rstrip(';:')
                        if last_w.lower() not in SENTENCE_END_FUNCTION_WORDS:
                            result = pre_quote
                            if len(result) > target_end:
                                result, tgt = _cleanup_unclosed_quote(
                                    result, target_word, target_offset)
                                if len(result) <= max_len and not _is_fragment(result):
                                    return result, tgt, True
                                d1_sentence = result
                                d1_tgt = tgt
                continue

    # Save original values for fallback — *sentence* is about to be
    # overwritten with d1_sentence which may be a fragment.  When both
    # Direction 1 and Direction 2 fail, the fallback must return the
    # ORIGINAL sentence, not the fragment-producing d1_sentence.
    _orig_sentence = sentence
    _orig_tgt = target_offset

    # Use Direction 1's best result (if any) as input to Direction 2.
    # Direction 1's right-truncated sentence is shorter, giving Direction 2
    # fewer chars to consider when scanning for left-side boundaries.
    if d1_sentence is not None:
        sentence = d1_sentence
        target_offset = d1_tgt
        target_end = target_offset + len(target_word)

    # ── Direction 2: scan left from target_offset for .!? boundaries ───
    # Find the nearest sentence boundary (".!?" + space + capital) before
    # the target word.  Scanning left gives the closest boundary = most
    # target-relevant context.
    best_start: int | None = None
    fallback_start: int | None = None
    for i in range(target_offset - 1, -1, -1):
        if sentence[i] not in '.!?':
            continue
        if i + 1 >= len(sentence):
            continue
        nxt = sentence[i + 1]
        if nxt == ' ' and i + 2 < len(sentence):
            if sentence[i + 2].isupper():
                new_start = i + 2
            elif sentence[i + 2] in ('"', "'") and i + 3 < len(sentence) and sentence[i + 3].isupper():
                new_start = i + 2   # . "X or . 'X → start at quote, keep passage intact
            else:
                continue
        elif nxt.isupper():
            new_start = i + 1
        elif nxt in ('"', "'") and i + 2 < len(sentence):
            nxt2 = sentence[i + 2]
            if nxt2 == ' ' and i + 3 < len(sentence) and sentence[i + 3].isupper():
                new_start = i + 3
            elif nxt2.isupper():
                new_start = i + 2
            else:
                continue
        else:
            continue
        if len(sentence) - new_start < len(sentence):  # actually shortens
            if fallback_start is None:
                fallback_start = new_start

            # Skip boundaries inside an unclosed double-quoted passage.
            # The ".!?" is dialogue-internal punctuation, not a
            # paragraph-level sentence boundary.
            if _is_inside_opening_quote(sentence, i):
                continue

            best_start = new_start
            break  # nearest balanced boundary = best context

    if best_start is None:
        best_start = fallback_start

    if best_start is not None:
        new_sentence = sentence[best_start:]
        new_target_offset = target_offset - best_start
        new_sentence, new_target_offset = _cleanup_unclosed_quote(
            new_sentence, target_word, new_target_offset)
        # If the result still has unbalanced quotes (e.g. fallback boundary
        # inside a quoted passage that _cleanup_unclosed_quote couldn't fix),
        # return the original sentence unchanged.  The caller will reject the
        # word rather than produce a fabricated or patched sentence.
        if new_sentence.count('"') % 2 != 0:
            return _orig_sentence, _orig_tgt, False
        return new_sentence, new_target_offset, True

    # Direction 2 found nothing.  If Direction 1 produced a valid result
    # (even if still > max_len), return it — it is shorter than the original.
    if d1_sentence is not None and not _is_fragment(d1_sentence):
        return d1_sentence, d1_tgt, True

    return _orig_sentence, _orig_tgt, False


def _has_be_to_pattern(doc, token_idx: int) -> bool:
    """Check if a token is a psychological adjective in 'be ADJ/VBN to VERB' pattern.

    E.g. 'was astonished to see', 'am surprised to hear'.
    Modern spaCy models (en_core_web_sm) often tag these as ADJ/JJ
    rather than VBN, so we accept both.
    """
    token = doc[token_idx]
    if token.tag_ not in ("VBN", "JJ"):
        return False
    # ADJ tokens: only check if dep is acomp/acmp/oprd (predicate adjective).
    # attr is for "X is Y" — not "be ADJ to VERB".
    if token.tag_ == "JJ" and token.dep_ not in ("acomp", "oprd"):
        return False
    be_forms = {'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being'}
    # Check for be-form before the token
    has_be = any(
        doc[i].text.lower() in be_forms
        for i in range(max(0, token_idx - 3), token_idx)
    )
    if not has_be:
        return False
    # Check for "to" after the token, followed by a VERB
    for j in range(token_idx + 1, min(token_idx + 3, len(doc))):
        if doc[j].text.lower() == 'to' and j + 1 < len(doc):
            if doc[j + 1].pos_ == 'VERB':
                return True
            break
    return False


def _determine_lemma(token, word: str) -> str:
    """Determine the lemma for a word based on spaCy token analysis.

    Returns the surface form (word) when it's an adjective or derivation
    that should not be reduced.  Otherwise passes to lemminflect with the
    correct POS channel.
    """
    import lemminflect

    wl = word.lower()

    # Signal 1: POS tag — spaCy directly tags as ADJ
    if token.pos_ == "ADJ":
        return wl

    # Signal 2: adjectival dependency relation.
    # attr is NOT included — it applies to both nouns and adjectives
    # in predicate position (e.g. "He is a teacher" vs "He is tall").
    if token.dep_ in ("acomp", "amod", "oprd"):
        return wl

    # Signal 3: VBG + adjectival dep — participial adjective
    if token.tag_ == "VBG" and token.dep_ in ("amod", "acomp"):
        return wl

    # Signal 4: PROPN — proper noun.  Lowercase PROPN is almost always
    # a spaCy mis-classification (genuine proper nouns are capitalised).
    # Sentence-initial tokens are also likely mis-classified (capitalised
    # due to position, not because they are proper nouns).
    # Must be checked BEFORE spacy_lemma==word (PROPN tokens lemma==text).
    if token.pos_ == "PROPN":
        if word[0].islower() or token.i == 0:
            lemmas = lemminflect.getLemma(wl, 'NOUN')
            if lemmas:
                lemma = lemmas[0]
                # COCA cross-check: if lemminflect produced a lemma that is
                # not in COCA but the surface form is, the lemmatizer likely
                # mis-parsed a loanword (e.g. "bonita" → "bonitum" — Spanish
                # fish name treated as Latin neuter).  Reject and keep the
                # surface form.
                in_coca_surface, _ = in_coca(wl)
                in_coca_lemma, _ = in_coca(lemma)
                if in_coca_surface and not in_coca_lemma:
                    return wl
                return lemma
        return word

    # Signal 5: spaCy lemma == surface form — refuses to reduce.
    # When spaCy tags a plural noun as NN (singular, e.g. "claws" in
    # "gripped claws of an eagle") the lemma equals the surface form.
    # The contradiction between plural-looking form (-s) and singular
    # tag (NN) is a reliable signal of a spaCy lemmatization error.
    # Try lemminflect NOUN channel — for genuine singular -s words
    # (news, means, campus) lemmas[0] returns the word itself.
    if token.lemma_.lower() == wl:
        if token.pos_ == "NOUN" and token.tag_ == "NN" and wl.endswith("s"):
            lemmas = lemminflect.getLemma(wl, 'NOUN')
            if lemmas and lemmas[0] != wl:
                return lemmas[0]
        return wl

    # Signal 6: ADV ending in -ly — don't reduce
    if token.pos_ == "ADV" and wl.endswith('ly'):
        return wl

    # lemminflect with the correct POS channel
    channel_map = {'VERB': 'VERB', 'NOUN': 'NOUN', 'ADJ': 'ADJ', 'ADV': 'ADV'}
    channel = channel_map.get(token.pos_)
    if channel:
        lemmas = lemminflect.getLemma(wl, channel)
        if lemmas:
            return lemmas[0]

    return wl


def _better(old: dict, new: dict) -> bool:
    """Return True if *new* sentence is better than *old*.

    Four-tier comparison (pure logic, no scoring):
      0. completeness: non-fragment beats fragment
      1. sweet-spot (MIN_SENTENCE_LENGTH-MAX_SENTENCE_LENGTH chars): shorter wins
      2. too-long (>MAX_SENTENCE_LENGTH): shorter wins
      3. too-short (<MIN_SENTENCE_LENGTH): longer wins
    Cross-tier: sweet-spot > too-long > too-short.
    Tie (same length): keep old.
    """
    # Tier 0 — completeness: non-fragment beats fragment
    old_frag = old.get('is_fragment', False)
    new_frag = new.get('is_fragment', False)
    if old_frag != new_frag:
        return not new_frag  # pick new only if it's complete

    la, lb = old['len'], new['len']
    if la == lb:
        return False                                             # tie → keep old
    if (la < MIN_SENTENCE_LENGTH or lb < MIN_SENTENCE_LENGTH) ^ (la < lb):
        return False                                             # keep old
    return True                                                  # pick new


def _sentence_char_offset(
    text: str, sentence: str, target_offset: int, start: int = 0,
    forms: list[str] | None = None,
) -> int:
    """Return absolute char offset of the target word by locating *sentence*
    in the source text, then searching for the word.

    Builds a whitespace-tolerant regex from the sentence so that
    normalization differences (newline→space, dialogue-attribution
    joining, double-space cleaning) don't prevent matching.

    When *forms* is provided, uses word-boundary search from the match
    position instead of adding *target_offset* directly — this avoids
    position drift caused by character-removing normalizations (e.g.
    ``_normalize_dialogue_attribution`` collapsing ``\\n\\n`` → `` ``).

    Returns the absolute offset, or -1 if the sentence cannot be found.
    """
    escaped = re.escape(sentence)
    # Allow any whitespace sequence in the source to match a single space
    # in the normalized sentence.
    flexible = re.sub(r'\\ ', r'\\s+', escaped)
    m = re.search(flexible, text[start:])
    if m:
        match_start = start + m.start()
        if forms:
            # Search for any form within the matched sentence extent
            # using word boundaries — robust against normalization
            # position drift.  Limit the search to the regex match
            # extent to avoid matching the same word in a later
            # sentence (e.g. "sardine" matching singular in a
            # different sentence when the current sentence has the
            # plural "sardines").
            match_end = start + m.end()
            search_text = text[match_start:match_end]
            for form in forms:
                if not form:
                    continue
                fm = re.search(r'\b' + re.escape(form) + r'\b',
                               search_text, re.IGNORECASE)
                if fm:
                    return match_start + fm.start()
            # No form found within the sentence — fall back to wider
            # search (handles edge cases where the flexible regex
            # matched a slightly different extent).
            for form in forms:
                if not form:
                    continue
                fm = re.search(r'\b' + re.escape(form) + r'\b',
                               text[match_start:], re.IGNORECASE)
                if fm:
                    return match_start + fm.start()
            return -1
        return match_start + target_offset
    return -1


def _first_word_boundary_offset(text: str, forms: list[str], start: int = 0) -> int:
    """Return char offset of the first \\b-bounded occurrence of any form.

    Uses word-boundary regex to avoid substring false matches
    (e.g. 'ram' matching inside 'grammar'). Returns -1 if no form found.
    """
    search_text = text[start:]
    for form in forms:
        if not form:
            continue
        m = re.search(r'\b' + re.escape(form) + r'\b', search_text, re.IGNORECASE)
        if m:
            return start + m.start()
    return -1


def _cmu_ipa(word: str) -> str:
    """Look up IPA from cmudict, with suffix-stripping fallback.

    Tries the exact word first.  If not found, strips common derivational
    suffixes (-ly, -ness, -ment, -tion, -sion) and retries the base form,
    appending the suffix's IPA.  Gracefully returns "" when neither the
    exact word nor its stripped base is in cmudict.
    """
    from lib.ipa import _cmu_ipa as _cmu_ipa_base

    result = _cmu_ipa_base(word)
    if result:
        return result

    w = word.lower()

    # British -our → -or fallback (e.g. discolour → discolor, honour → honor).
    # Common in Internet Archive / Project Gutenberg texts.  Only fires when
    # the original word is not in cmudict.
    if "our" in w:
        us_form = w.replace("our", "or")
        if us_form != w:
            result = _cmu_ipa_base(us_form)
            if result:
                return result

    # Ordered: most common suffix first; -ly adverbs are the primary target.
    suffixes: list[tuple[str, str, str]] = [
        ("ly",   "ly",   "/li/"),    # indulgently → indulgent + /li/
        ("ness", "ness", "/nəs/"),   # happiness   → happy     + /nəs/
        ("ment", "ment", "/mənt/"),  # enjoyment   → enjoy     + /mənt/
        ("tion", "tion", "/ʃən/"),   # education   → educate   + /ʃən/
        ("sion", "sion", "/ʒən/"),   # decision    → decide    + /ʒən/
        ("ion",  "ion",  "/ʃən/"),   # dejection   → deject    + /ʃən/
    ]
    for sfx, _strip, append_ipa in suffixes:
        if w.endswith(sfx) and len(w) > len(sfx) + 1:
            base_form = w[:-len(sfx)]
            base_ipa = _cmu_ipa_base(base_form)
            # y→i spelling change: thriftily → thrifti → thrifty
            if not base_ipa and sfx == "ly" and base_form.endswith("i"):
                base_ipa = _cmu_ipa_base(base_form[:-1] + "y")
            # -ble → -bly: perceptibly → strip ly → perceptib → +le → perceptible
            # (also: probably → probab → +le → probable)
            if not base_ipa and sfx == "ly" and base_form.endswith("b"):
                base_ipa = _cmu_ipa_base(base_form + "le")
            # -tion → -te: undulation → undula → undulate
            if not base_ipa and sfx == "tion":
                base_ipa = _cmu_ipa_base(base_form + "te") or _cmu_ipa_base(base_form + "e")
            if base_ipa:
                return base_ipa.rstrip("/") + append_ipa.lstrip("/")

    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Step 2A: Match vocabulary words to source sentences, "
                    "extract POS via spaCy, and generate cmudict IPA."
    )
    parser.add_argument(
        "filter_json",
        help="JSON file from filter_fulltext.py or filter_pipeline.py "
             "(must contain 'in_coca' key with word entries)",
    )
    parser.add_argument(
        "source_text",
        help="Plain text of the book (English, full text)",
    )
    parser.add_argument(
        "--start-offset", type=int, default=0,
        help="Character offset to skip (preamble detection runs if 0; "
             "pass -1 to disable preamble detection)",
    )
    parser.add_argument(
        "--end-offset", type=int, default=None,
        help="Character offset to stop (exclusive). When set, only text "
             "[start_offset:end_offset] is searched for sentences. "
             "Use with --start-offset to limit sentence matching to a "
             "specific chapter range. Default: search to end of file.",
    )
    parser.add_argument(
        "--json-out",
        help="Write JSON output to PATH instead of stdout",
    )
    parser.add_argument(
        "--book-title",
        help="Override book title (if missing or empty in input JSON)",
    )
    parser.add_argument(
        "--book-author",
        help="Override book author (if missing or empty in input JSON)",
    )
    args = parser.parse_args()

    json_path = args.filter_json
    text_path = args.source_text

    try:
        with open(json_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: JSON file not found: {json_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {json_path}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(text_path) as f:
            text = f.read()
    except FileNotFoundError:
        print(f"ERROR: Source text file not found: {text_path}", file=sys.stderr)
        sys.exit(1)

    # Structural JSON validation
    if "in_coca" not in data:
        print(
            f"ERROR: {json_path} is missing 'in_coca' key. "
            f"Is this the right file? Expected output from filter_fulltext.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(data["in_coca"], list):
        print(f"ERROR: 'in_coca' in {json_path} is not a list.", file=sys.stderr)
        sys.exit(1)
    for i, entry in enumerate(data["in_coca"]):
        if "forms" not in entry:
            print(
                f"ERROR: Entry {i} ({entry.get('lemma', '?')}) in 'in_coca' "
                f"is missing 'forms' key.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Reject non-English source texts
    if re.search(r'[Ѐ-ӿ«»]', text):
        print("ERROR: Source text contains Cyrillic or guillemet characters.",
              file=sys.stderr)
        sys.exit(1)

    # Validate plain-text format (defence-in-depth against HTML wrappers)
    from lib.utils import validate_plain_text
    validate_plain_text(text, text_path)

    output = process_words(
        data, text,
        start_offset=args.start_offset,
        end_offset=args.end_offset,
        book_title=args.book_title,
        book_author=args.book_author,
        source_text_path=text_path,
    )

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


_NON_BODY_PATTERNS = [
    # ALL CAPS title list / bibliography: ≥25 chars, all uppercase letters
    # (with spaces, apostrophes, hyphens).  Excludes short headings like
    # "CHAPTER I" (too short) or normal dialogue ALL CAPS words.
    (re.compile(r'^[A-Z][A-Z\s\'\-]{24,}$'), "all_caps_title"),
    # Copyright / legal boilerplate — matched case-insensitively against
    # the first line of the sentence.
    (re.compile(r'(?i)\b(?:COPYRIGHT|DISTRIBUTE|PROOFREADER|REDISTRIBUTE)\b'), "copyright"),
    # Producer / transcriber credit lines that appear at the start or end
    # of Project Gutenberg / Distributed Proofreaders texts.
    (re.compile(r'(?i)(?:^(?:Produced by|Distributed Proofreaders|A Distributed Proofreaders)|\bproduced\s+by\b)'), "producer_credit"),
    # Dedication: "TO …" with ≤6 words (short lines, no body-text content).
    (re.compile(r'^TO\s+(?:\w+\s*){1,6}$'), "dedication"),
    # End-of-text markers: "[End of …]", "End of the Project …", etc.
    (re.compile(r'^\[?End\s+of\s+(the\s+)?'), "end_marker"),
]


def _is_non_body_text(sentence: str) -> bool:
    """Return True if *sentence* comes from a non-body-text section.

    Checks mechanical patterns only — no hard-coded word lists.
    Matches against the first non-empty line of the sentence.
    """
    first_line = sentence.split('\n')[0].strip()
    if not first_line:
        return False
    for pattern, _reason in _NON_BODY_PATTERNS:
        if pattern.search(first_line):
            return True
    return False


def process_words(
    data: dict,
    text: str,
    start_offset: int = 0,
    end_offset: int | None = None,
    book_title: str | None = None,
    book_author: str | None = None,
    source_text_path: str = "",
    nlp=None,
) -> dict:
    """Run the full sentence-matching pipeline on *data* against *text*.

    This is the core of Step 2A — usable both from the CLI (via ``main()``)
    and programmatically from tests or scripts.  *nlp* is an optional
    pre-loaded spaCy model; if omitted, one is loaded automatically.
    """
    # ── load spaCy (if not provided) ────────────────────────────────────
    if nlp is None:
        import spacy
        from lib.utils import _get_spacy
        nlp = _get_spacy(enable_parser=True)
        if nlp is None:
            raise RuntimeError("spaCy not available")

    # ── quote normalisation ────────────────────────────────────────────
    text = normalize_quotes(text)

    # ── preamble detection ──────────────────────────────────────────────
    if start_offset == 0:
        story_start = detect_story_start(text)
        if story_start > 0:
            print(f"  [info] Preamble skipped: {story_start} chars", file=sys.stderr)
            start_offset = story_start
    elif start_offset < 0:
        start_offset = 0

    words = data['in_coca']
    total = len(words)

    # ── Step 1: split sentences once ─────────────────────────────────────
    if end_offset is not None:
        source_slice = text[start_offset:end_offset]
        sentences = split_sentences(source_slice, source_slice)
    else:
        source_slice = text[start_offset:]
        sentences = split_sentences(source_slice, source_slice)
    text_normalized = _strip_non_alpha(text)
    print(f"  Sentences: {len(sentences)}", file=sys.stderr)

    # Pre-compute set of all-lowercase words in source text.  Used by
    # PROPN→NOUN conversion: a word that appears in lowercase elsewhere
    # is a common noun (spaCy mis-tagged it PROPN).  A word that never
    # appears lowercase (e.g. planet names) is a genuine proper noun.
    _all_lowercase_words: set[str] = set(
        t.lower() for t in re.findall(r'\b[a-z]{2,}\b', text)
    )

    # ── Step 2: build form → [(idx, entry)] index ───────────────────────
    form_index: dict[str, list[tuple[int, dict]]] = {}
    for idx, entry in enumerate(words):
        for form in entry['forms']:
            key = form.lower()
            if key not in form_index:
                form_index[key] = []
            form_index[key].append((idx, entry))

    # ── Step 3: incremental best-entry state ────────────────────────────
    groups: dict[tuple[str, str], dict] = {}       # (lemma, pos) → best entry
    group_sources: dict[tuple[str, str], set] = {}  # (lemma, pos) → set of word indices
    matched_indices: set = set()

    # ── Step 4: single pass over sentences ──────────────────────────────
    TOTAL_SENTS = len(sentences)
    for si, raw_sentence in enumerate(sentences):
        # --- normalise whitespace ---
        sentence = re.sub(r' {2,}', ' ', raw_sentence)
        sentence = re.sub(r'\t+', ' ', sentence).strip()
        if not sentence:
            continue

        # --- pre-filter: quick token match before running spaCy ---
        pre_tokens = set(
            t.lower() for t in re.findall(r'\b[a-zA-Z]{2,}\b', sentence)
        )
        if not any(t in form_index for t in pre_tokens):
            continue

        # --- source-text verification (pre-truncation) ---
        if _strip_non_alpha(sentence) not in text_normalized:
            continue

        # --- regex: find all target word occurrences in the full sentence ---
        # Pipeline: smart_truncate runs FIRST on the full sentence, then spaCy
        # only processes the already-truncated short text.
        seen_entries: set[int] = set()  # (idx, token.text.lower()) per sentence
        for form_lower, hits in form_index.items():
            for m in re.finditer(r'\b' + re.escape(form_lower) + r'\b', sentence, re.IGNORECASE):
                matched_form = m.group()
                tgt_offset = m.start()

                # --- smart_truncate on full sentence BEFORE spaCy ---
                short_sent, new_tgt, was_trunc = smart_truncate(
                    sentence, matched_form, tgt_offset,
                )

                # Reject words whose sentence is still too long after truncation
                if len(short_sent) > HARD_CUTOFF:
                    continue

                # --- spaCy on the already-truncated short text ---
                doc = nlp(short_sent)

                # Find the spaCy token at new_tgt position
                token = None
                for t in doc:
                    if t.idx == new_tgt and t.is_alpha and len(t.text) >= 2:
                        token = t
                        break
                if token is None:
                    continue  # spaCy didn't tokenize this as expected

                token_lower = token.text.lower()

                # The form was already matched by regex — verify via form_index
                hits = form_index.get(token_lower)
                if not hits:
                    continue

                # Skip compound tokens inside hyphenated compounds
                # (e.g. "mast" in "mast-head").
                if token.dep_ == "compound":
                    head = token.head
                    if token.i < head.i:
                        gap = short_sent[token.idx + len(token.text):head.idx]
                    else:
                        gap = short_sent[head.idx + len(head.text):token.idx]
                    if gap.startswith("-") or gap.endswith("-"):
                        continue
                if token.i > 0 and doc[token.i - 1].text == "-":
                    continue

                for idx, entry in hits:
                    # Prevent re-processing the same (entry index, token text)
                    # within the same sentence (e.g. "walked" appearing twice).
                    sent_key = (idx, token_lower)
                    if sent_key in seen_entries:
                        continue
                    seen_entries.add(sent_key)

                    # Determine lemma from this specific token context
                    lemma = _determine_lemma(token, token.text)
                    pos = token.pos_

                    # be-to pattern check for VBN tokens.
                    # Run unconditionally — even when _determine_lemma already
                    # returned the surface form (via other ADJ signals), we
                    # need be_to=True in the output.  Only override lemma/POS
                    # when _determine_lemma did NOT already do so.
                    has_be_to = (
                        token.tag_ in ("VBN", "JJ")
                        and _has_be_to_pattern(doc, token.i)
                    )
                    if has_be_to and lemma != token_lower:
                        lemma = token_lower
                        pos = "ADJ"

                    # PROPN→NOUN: convert spaCy PROPN tags for words in our
                    # vocabulary — most are common nouns mis-capitalized
                    # (sentence-initial, mid-sentence like "Boa constrictors").
                    # Genuine proper nouns are protected by the revert block
                    # below: if the word never appears in lowercase anywhere
                    # in the text and has no adjective signals, it stays PROPN.
                    _was_propn = (pos == "PROPN")
                    if pos == "PROPN" and (token.text[0].islower() or token.i == 0
                                           or token_lower in form_index):
                        pos = "NOUN"
                    # Shared set: verbal dependents that indicate a genuine
                    # clause structure (subjects, objects, agents).
                    # Hoisted here so both conj-chain and later VBN rules
                    # can use it.  Adverbial modifiers and determiners are
                    # not verbal arguments — a bare VBN with only non-verbal
                    # children is adjectival.
                    _VERBAL_DEPS = frozenset({
                        "nsubj", "csubj", "dobj", "iobj", "pobj",
                        "xcomp", "ccomp", "aux", "auxpass", "agent",
                        "expl", "nsubjpass",
                    })
                    # conj POS inheritance: in coordinated structures
                    # (A, B, C and D), spaCy sometimes mis-tags individual
                    # conjuncts (e.g. "arithmetic" as ADJ in a list of NOUNs).
                    # Walk up the conj chain to the coordination root and
                    # inherit its POS when the root has a reliable POS tag.
                    if token.dep_ == "conj":
                        head_token = token.head
                        walked_past_content = False
                        while head_token.dep_ in ("conj", "cc"):
                            if head_token.dep_ == "conj":
                                walked_past_content = True
                            head_token = head_token.head
                        head_pos = head_token.pos_
                        # When the chain root is a VERB in acl/amod position,
                        # it is an adjectival participle modifier — not a true
                        # verbal coordination root.  E.g. "the formalized,
                        # iridescent, gelatinous bladder" → "formalized"(VBN,acl)
                        # chains to "bladder"(NOUN,conj).  Inheriting VERB from
                        # an adjectival modifier would incorrectly convert the
                        # noun to a verb.  Skip the inheritance.
                        if (head_pos == "VERB"
                                and head_token.dep_ in ("acl", "amod")):
                            pass
                        elif head_pos in ("NOUN", "VERB", "ADJ", "ADV") and pos != head_pos:
                            # Don't promote a spaCy-tagged NOUN to VERB via conj
                            # inheritance.  A NOUN directly conjoined to a VERB
                            # (e.g. "fins" conj of "see" in "see...heads and...fins")
                            # is a coordinated argument, not a verb.  spaCy's own
                            # POS tag (NOUN) is more trustworthy than the chain root.
                            if head_pos == "VERB" and token.pos_ == "NOUN":
                                pass
                            elif (head_pos == "NOUN" and pos == "VERB"
                                  and (any(c.dep_ in _VERBAL_DEPS
                                           for c in token.children)
                                       or (token.tag_ == "VBG"
                                           and not any(c.dep_ == "det"
                                                       for c in token.children)))):
                                # Don't demote a spaCy-tagged VERB to NOUN via
                                # conj inheritance when the token has verbal
                                # dependents (dobj, nsubj, etc.) or is a
                                # present participle (VBG) without a determiner.
                                # E.g. "paralyzed"(VBD,conj,dobj="leg") → verb.
                                # "crouching"(VBG,conj,no-det) → verb.
                                # VBG guard: spaCy tags present participles
                                # as VBG when they are verbal; nominal gerunds
                                # are tagged NN.  A VBG without a determiner
                                # child should not be demoted to NOUN.
                                # det-child gate: "the hissing"(VBG,det="the")
                                # IS a nominal gerund → allow NOUN inheritance.
                                pass
                            elif head_pos == "ADJ" and any(
                                c.dep_ == "det" for c in token.children
                            ):
                                # Token has a determiner child ("a", "the") →
                                # unambiguously a noun head.  Do not promote
                                # NOUN → ADJ via conj inheritance from an
                                # adjectival chain root.
                                pass
                            else:
                                pos = head_pos
                            # When inheriting ADJ via conj chain, ensure lemma is
                            # the surface form — _determine_lemma may have reduced
                            # a VBN/VBD token via the VERB channel (e.g. "tempered"
                            # → "temper"), and the ADJ lemma should be the surface
                            # form (e.g. "tempered" conj of "sharp" → ADJ).
                            if pos == "ADJ" and token.tag_ in ("VBD", "VBN"):
                                lemma = token_lower
                            # When the coordination root is VBN/VBD in advcl
                            # position with no verbal dependents, it is a
                            # depictive predicate adjective — the conjunct
                            # shares this adjectival role.
                            # E.g. "Drained of blood and awash he looked..."
                            # → "awash"(NOUN,conj,head=Drained(VBN,advcl)).
                            # "Drained" has only prep/cc/conj children → ADJ.
                            if (head_pos == "VERB"
                                    and head_token.tag_ in ("VBD", "VBN")
                                    and head_token.dep_ == "advcl"):
                                verbal_children = [
                                    c for c in head_token.children
                                    if c.dep_ in _VERBAL_DEPS
                                ]
                                if not verbal_children:
                                    pos = "ADJ"
                                    lemma = token_lower
                        elif head_pos == "AUX" and not walked_past_content:
                            # Direct conjunction of copula: "was thin and gaunt".
                            # Only fires when the token is a direct child of the
                            # AUX (no intermediate content-word conj nodes walked
                            # past).  If the chain passed through a VERB/NOUN/etc,
                            # the token is coordinated with that content word,
                            # not with the adjective complement.
                            # Guard: if the token has its own subject (nsubj,
                            # nsubjpass, csubj), it heads a separate clause —
                            # NOT a copula complement sharing the copula's
                            # subject.  E.g. "He was tired and he teetered" →
                            # "teetered" has nsubj "he" → stays VERB.
                            has_own_subject = any(
                                c.dep_ in ("nsubj", "nsubjpass", "csubj")
                                for c in token.children
                            )
                            if not has_own_subject:
                                # Only nouns can have determiner children ("a",
                                # "the", "my").  If the token has a det child, it
                                # heads a noun phrase — do NOT promote it to ADJ
                                # even when conjoined to a copula whose complement
                                # is an adjective.
                                if not any(c.dep_ == "det" for c in token.children):
                                    for child in head_token.children:
                                        if child.dep_ in ("acomp", "amod") and child.pos_ == "ADJ":
                                            pos = "ADJ"
                                            lemma = token_lower
                                            break
                    # Sentence-initial inverted ADJ: "Absurd as it might seem"
                    # (= "As absurd as ...").  spaCy often tags these as PROPN
                    # (capitalized at sentence start); PROPN→NOUN then converts
                    # to NOUN.  Detect the "X as" pattern with dep guard
                    # (advcl for inverted adjective clauses, not npadvmod for
                    # noun phrases like "King as he was").
                    if (pos == "NOUN" and token.i == 0
                            and token.dep_ in ("advcl", "root", "ROOT")):
                        if (token.i + 1 < len(doc)
                                and doc[token.i + 1].text.lower() == "as"):
                            import lemminflect
                            adj_lemmas = lemminflect.getLemma(token_lower, 'ADJ')
                            if adj_lemmas and adj_lemmas[0] == token_lower:
                                pos = "ADJ"
                    # ADV→NOUN: dep=dobj contradicts ADV (dobj requires a nominal).
                    # If spaCy tagged a word as ADV but assigned it a direct-object
                    # dependency, the token is almost certainly a NOUN.
                    if pos == "ADV" and token.dep_ == "dobj":
                        pos = "NOUN"
                    # ADJ→NOUN: pobj/dobj contradicts ADJ (both require a nominal).
                    # A prepositional object or direct object must be nominal —
                    # an adjective with these deps is always a spaCy mis-tag.
                    # Covers "odour" (ADJ+pobj in "edge of the odour") and
                    # "stern" (ADJ+pobj in "back in the stern" = boat stern).
                    if pos == "ADJ" and token.dep_ in ("pobj", "dobj"):
                        pos = "NOUN"
                    # NOUN/VERB→ADJ: adjectival dependency overrides POS tag.
                    # attr is excluded — it applies to both nouns ("a teacher")
                    # and adjectives ("tall") in predicate position.
                    # NOUN+amod/acomp/oprd covers rare spaCy errors where a true
                    # adjective is mis-tagged as NOUN.  Common attributive nouns
                    # ("oar handle", "slant change") are typically tagged ADJ by
                    # spaCy directly (this rule does not fire for them).
                    if pos in ("NOUN", "VERB") and token.dep_ in ("amod", "acomp", "oprd"):
                        pos = "ADJ"
                    # NOUN+dobj→ADJ when a coordinated ADJ child signals that the
                    # head is also adjectival (e.g. "rest there slimy and purple"
                    # → slimy NOUN/dobj but purple ADJ/conj — both should be ADJ).
                    # Gated on -y suffix (common adjective marker) and the
                    # presence of an ADJ/conj child (coordinated adjective).
                    if (pos == "NOUN" and token.dep_ == "dobj"
                            and token_lower.endswith("y")):
                        for child in token.children:
                            if child.dep_ == "conj" and child.pos_ == "ADJ":
                                pos = "ADJ"
                                lemma = token_lower
                                break
                    # VBN + preceding ADV advmod child → ADJ: a preposed true adverb
                    # directly modifying a past participle is a strong signal of
                    # adjectival usage (e.g. "completely abashed", "very surprised").
                    # Non-ADV advmods (subordinators like "When", particles like
                    # "along") and postposed adverbs do NOT trigger this rule.
                    # In UD, manner adverbs modifying genuine passive verbs
                    # attach to the auxiliary, not the participle.
                    #
                    # Guard: aux child (has/have/had) → perfect tense verb.
                    #   "had just summoned" — "just" is ADV+advmod, but "had"
                    #   as aux indicates the VBN is a perfect-tense main verb,
                    #   not an adjective.  aux + VBN is exclusively verbal.
                    if (pos == "VERB" and token.tag_ == "VBN"
                            and not any(c.dep_ == "aux" for c in token.children)):
                        for child in token.children:
                            if (child.dep_ == "advmod"
                                    and child.pos_ == "ADV"
                                    and child.i < token.i):
                                pos = "ADJ"
                                lemma = token_lower
                                break
                    # VBD/VBN + advcl + no verbal dependents → ADJ.
                    # A lone past participle in advcl position with no
                    # verbal children (subjects, objects, agents) is a
                    # depictive predicate adjective, not a true adverbial
                    # clause.  E.g. "went away, puzzled." or
                    # "Clad in royal purple, he was seated..."
                    # Prepositional-phrase modifiers (in+N, on+N) are
                    # typical of adjectives, not verbal clauses.
                    # Exclude VBG (present participles like "smiling") —
                    # more often verbal.
                    if (pos == "VERB" and token.dep_ == "advcl"
                            and token.tag_ in ("VBD", "VBN")):
                        verbal_children = [
                            c for c in token.children
                            if c.dep_ in _VERBAL_DEPS
                        ]
                        if not verbal_children:
                            pos = "ADJ"
                            lemma = token_lower
                    # VBD/VBN + advmod + no verbal dependents → ADJ.
                    # A lone past participle as an adverbial modifier (no comma)
                    # with only non-verbal children is a depictive predicate
                    # adjective.  E.g. "stood there all bewildered."
                    # Exclude VBG — present participles are more often genuinely
                    # verbal.  Exclude tokens with verbal children — true
                    # adverbial clauses have structure; a bare participle is
                    # adjectival.
                    if (pos == "VERB" and token.dep_ == "advmod"
                            and token.tag_ in ("VBD", "VBN")):
                        verbal_children = [
                            c for c in token.children
                            if c.dep_ in _VERBAL_DEPS
                        ]
                        if not verbal_children:
                            pos = "ADJ"
                            lemma = token_lower
                    # PROPN→NOUN revert: genuine proper nouns (Jupiter, Mars,
                    # Venus) were converted to NOUN by form_index membership.
                    # They never appear in lowercase in the text and have no
                    # adjective signals — revert them to PROPN.
                    # Sentence-initial tokens are exempt: capitalization may be
                    # positional, not a genuine proper-noun signal.
                    if (_was_propn and pos == "NOUN" and token.i != 0
                            and token_lower not in _all_lowercase_words):
                        pos = "PROPN"

                    # Mid-sentence capitalized NOUN → PROPN.  In English, a
                    # common noun capitalised mid-sentence is almost always a
                    # proper noun (e.g. "the Terrace", "Gulf Stream").  Only
                    # fires when spaCy originally tagged the token as NOUN
                    # (not PROPN→NOUN conversions — those were intentional).
                    # Skip quote-initial tokens (preceded by a quotation mark)
                    # — the capitalisation is positional, not a proper-noun signal.
                    if (not _was_propn and pos == "NOUN" and token.i != 0
                            and token.text and token.text[0].isupper()
                            and doc[token.i - 1].text not in ('"', '"', '"', "'", "'")):
                        pos = "PROPN"

                    key = (lemma.lower(), pos)

                    # smart_truncate already ran on the full sentence before
                    # spaCy — the sentence IS the truncated version.
                    cand = {
                        'text': short_sent,
                        'len': len(short_sent),
                        'target_offset': new_tgt,
                        'matched_form': token.text,
                        'lemma': lemma,
                        'pos': pos,
                        'dep': token.dep_,
                        'spacy_lemma': token.lemma_,
                        'be_to': has_be_to,
                        'is_fragment': _is_fragment(short_sent),
                    }

                    if key not in groups or _better(groups[key], cand):
                        groups[key] = cand

                    if key not in group_sources:
                        group_sources[key] = set()
                    group_sources[key].add(idx)
                    matched_indices.add(idx)

    print(f"\r  {si+1}/{TOTAL_SENTS}", end='', file=sys.stderr, flush=True)

    print(file=sys.stderr)

    # ── Step 5: post-process output ─────────────────────────────────────
    results = []
    for key, cand in groups.items():
        lemma, pos = key
        indices = group_sources.get(key, set())

        # Merge forms from all source entries
        all_forms: list[str] = []
        for idx in indices:
            entry = words[idx]
            for f in entry['forms']:
                fl = f.lower()
                if fl not in all_forms:
                    all_forms.append(fl)
        all_forms.sort()

        # coca_level from first source entry that has one
        coca_level = None
        for idx in indices:
            lvl = words[idx].get('coca_level')
            if lvl is not None:
                coca_level = lvl
                break

        # char_offset: locate the selected sentence in the source text,
        # then add target_offset.  Falls back to first word-boundary
        # match when sentence-based search fails (edge case, e.g. when
        # hard truncation or unusual whitespace prevents matching).
        char_offset = _sentence_char_offset(
            text, cand['text'], cand['target_offset'], start_offset,
            forms=all_forms,
        )
        if char_offset < 0:
            char_offset = _first_word_boundary_offset(text, all_forms, start_offset)

        # Skip entries whose matched sentence comes from non-body-text
        # sections (bibliography, copyright, dedication, etc.).
        if _is_non_body_text(cand['text']):
            continue

        # Sentence already truncated by smart_truncate in Step 4.
        sent_text = cand['text']
        tgt_offset = cand['target_offset']

        # IPA: try lemma first, fall back to matched surface form
        ipa = _cmu_ipa(lemma) or _cmu_ipa(cand['matched_form'])

        entry = {
            'lemma': cand['lemma'] if cand['pos'] == 'PROPN' else cand['lemma'].lower(),
            'word': cand['matched_form'],
            'forms': all_forms,
            'pos': cand['pos'],
            'dep': cand.get('dep', ''),
            'spacy_lemma': cand.get('spacy_lemma', ''),
            'be_to': cand.get('be_to', False),
            'coca_level': coca_level,
            'sentence': sent_text,
            'target_offset': tgt_offset,
            'char_offset': char_offset,
            'ipa': ipa,
        }
        if _is_fragment(sent_text):
            entry['is_fragment'] = True
        results.append(entry)

    # Sort results for deterministic output (by lemma, then pos)
    results.sort(key=lambda r: (r['lemma'], r['pos']))

    # Report unmatched filter entries, categorized by reason:
    #   1. "covered by" — lemma already matched via another surface form
    #   2. "not in source" — none of the word's forms appear in the source text
    #   3. "no suitable sentence" — forms exist in text but no sentence selected
    matched_lemmas: set[str] = {lemma.lower() for (lemma, _pos) in groups}
    no_sentence: list[tuple[str, list[str], str]] = []  # (lemma, forms, reason)
    for idx, entry in enumerate(words):
        if idx in matched_indices:
            continue
        lemma = entry.get('lemma', '')
        forms = entry.get('forms', [])
        # Check if lemma already covered by another surface form
        if lemma.lower() in matched_lemmas:
            no_sentence.append((lemma, forms, 'covered_by_lemma'))
        # Check if any form appears anywhere in the source text
        elif not any(_form_found_in_text(f, text) for f in forms):
            no_sentence.append((lemma, forms, 'not_in_source'))
        else:
            no_sentence.append((lemma, forms, 'no_sentence'))

    if no_sentence:
        covered = [(l, f) for l, f, r in no_sentence if r == 'covered_by_lemma']
        not_in_src = [(l, f) for l, f, r in no_sentence if r == 'not_in_source']
        no_sent = [(l, f) for l, f, r in no_sentence if r == 'no_sentence']
        print(f"\nUnmatched entries ({len(no_sentence)}):", file=sys.stderr)
        for label, items in [
            ("Covered by alternative form", covered),
            ("Not found in source text", not_in_src),
            ("No suitable sentence", no_sent),
        ]:
            if items:
                print(f"  {label} ({len(items)}):", file=sys.stderr)
                for surface, forms in items:
                    print(f"    [{surface}] forms={forms}", file=sys.stderr)

    print(f"  Words matched: {len(matched_indices)}/{total} → {len(results)} (lemma,pos) groups",
          file=sys.stderr)

    return {
        'book_title': book_title if book_title else data.get('book_title', ''),
        'book_author': book_author if book_author else data.get('book_author', ''),
        'deck_name': data.get('deck_name', ''),
        'source_text_path': source_text_path,
        'book_id': data.get('book_id', ''),
        'suffix': data.get('suffix', ''),
        'bands': data.get('bands', []),
        'is_bilateral': data.get('is_bilateral', False),
        'words': results,
        'excluded': data.get('excluded', []),
    }


if __name__ == '__main__':
    main()
