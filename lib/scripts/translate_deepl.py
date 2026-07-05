#!/usr/bin/env python3
"""Translate sentences via DeepL API.

Reads a vocab-anki JSON file, strips <b> tags from sentences, translates
them via DeepL, and writes the result to an output file (default: overwrites
input file).

Usage:
    python scripts/translate_deepl.py input.json
    python scripts/translate_deepl.py input.json --output output.json
    python scripts/translate_deepl.py input.json --book-context "Title: ..."

Requires DEEPL_API_KEY environment variable (free key from deepl.com/pro-api).
Free tier: 500,000 chars/month, api-free.deepl.com endpoint.

DeepL does not support <b> tags natively. We strip them before sending,
then DeepL's output naturally includes the word in translation context.
"""

import argparse
import json
import os
import re
import sys

import deepl
import pysbd

DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "")
if not DEEPL_API_KEY:
    print("ERROR: DEEPL_API_KEY environment variable not set.", file=sys.stderr)
    sys.exit(1)

translator = deepl.Translator(DEEPL_API_KEY)
def _build_sentence_regex(sentence: str) -> str:
    """Build a regex from sentence words joined by \\s+ for fuzzy matching.

    Strips punctuation from each word so \"ephemeral,\" in the truncated
    sentence matches \"ephemeral\" in the source text. Handles newlines,
    straight/curly quotes, and minor punctuation differences.
    """
    import string
    _PUNCT = string.punctuation + '“”‘’…—–'
    words = []
    for w in sentence.split():
        w = w.strip(_PUNCT)
        if w:
            words.append(re.escape(w))
    # Join with [^\w]* to swallow any non-word chars between words
    # (punctuation, whitespace, newlines, quotes).  \s+ alone misses
    # "I, too" (comma after I) or "tenderness \nand" (newline).
    return r'[^\w]*'.join(words)


CONTEXT_SENTENCES = 2  # sentences before target to include as context


def strip_tags(text: str) -> str:
    """Remove <b> markup, keeping the inner text."""
    return re.sub(r"</?b>", "", text)


def translate_batch(
    texts: list[str],
    context: str = "",
) -> list[str]:
    """Translate a batch of texts via DeepL API. Returns translations in order.

    If context is provided, it is sent as the DeepL 'context' parameter —
    surrounding text that helps disambiguate but is NOT translated itself
    (free, no char cost). Same context applies to all texts in the batch.
    """
    kwargs: dict = {"target_lang": "ZH"}
    if context:
        kwargs["context"] = context

    try:
        result = translator.translate_text(texts, **kwargs)
        if isinstance(result, list):
            return [r.text for r in result]
        return [result.text]
    except deepl.DeepLException as e:
        print(f"  DeepL error: {e}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Translate sentences via DeepL API"
    )
    parser.add_argument("input_file", help="JSON input file with word entries")
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output JSON file (default: overwrite input file)",
    )
    parser.add_argument(
        "--source-text", type=str, default=None,
        help="Path to source book text file. If provided, surrounding "
             "sentences are sent as DeepL context parameter (free, no "
             "char cost) to improve translation accuracy.",
    )
    args = parser.parse_args()
    json_path = args.input_file

    if not os.path.exists(json_path):
        print(f"Error: file not found: {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # Load source text for context extraction.
    source_sentences: list[str] = []
    if args.source_text and os.path.exists(args.source_text):
        with open(args.source_text, encoding="utf-8") as f:
            src_text = f.read()
        seg = pysbd.Segmenter(language="en", clean=True)
        # Normalize newlines like match_sentences.py
        src_text = re.sub(r'\n{2,}', '\n\n', src_text)
        src_text = re.sub(r'(?<!\n)\n(?!\n)', ' ', src_text)
        source_sentences = seg.segment(src_text)
        source_sentences = [s.strip() for s in source_sentences if s.strip()]

    words = data.get("words", [])
    if not words:
        print("No words to translate.", file=sys.stderr)
        return

    # Collect unique sentences (dedup by plain text without <b> tags).
    # Multiple words may share the same sentence — translate once, apply to all.
    unique: dict[str, tuple[list[int], str]] = {}  # plain → ([indices], context)
    sentence_order: list[str] = []  # preserve order
    for i, w in enumerate(words):
        plain = strip_tags(w.get("sentence", "")).strip()
        if not plain:
            continue
        if plain not in unique:
            sentence_order.append(plain)
            context = ""
            if source_sentences:
                pattern = re.compile(
                    _build_sentence_regex(plain), re.IGNORECASE,
                )
                for si, src_s in enumerate(source_sentences):
                    if pattern.search(src_s):
                        start = max(0, si - CONTEXT_SENTENCES)
                        ctx_sents = source_sentences[start:si]
                        if ctx_sents:
                            context = " ".join(ctx_sents)
                        break
            unique[plain] = ([i], context)
        else:
            unique[plain][0].append(i)

    to_translate = [
        (plain, context) for plain in sentence_order
        if plain in unique
    ]
    deduped = len(words) - len(to_translate)
    if deduped:
        print(f"  (deduplicated {deduped} sentences)", file=sys.stderr)
    total = len(to_translate)
    if total == 0:
        print("No sentences to translate.", file=sys.stderr)
        return

    print(f"Translating {total} sentences via DeepL (batch size 50)...", file=sys.stderr)

    BATCH_SIZE = 50
    translated_count = 0
    errors = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = to_translate[batch_start:batch_start + BATCH_SIZE]
        texts = [t[0] for t in batch]
        # Split: items with context go individually, items without
        # go as a batch for speed.
        ctx_batch = [(txt, ctx) for txt, ctx in batch if ctx]
        no_ctx_batch = [(txt, ctx) for txt, ctx in batch if not ctx]

        # Batch items without context
        if no_ctx_batch:
            try:
                no_ctx_texts = [t[0] for t in no_ctx_batch]
                translations = translate_batch(no_ctx_texts)
                for (plain, _), trans in zip(no_ctx_batch, translations):
                    for idx in unique[plain][0]:
                        words[idx]["translation_cn"] = trans
                    translated_count += 1
            except Exception as e:
                errors += 1
                print(f"  Batch failed: {e}", file=sys.stderr)

        # Individual items with context
        for (plain_text, context) in ctx_batch:
            try:
                results = translate_batch([plain_text], context=context)
                for idx in unique[plain_text][0]:
                    words[idx]["translation_cn"] = results[0]
                translated_count += 1
            except Exception:
                errors += 1
                # Retry without context
                try:
                    results = translate_batch([plain_text])
                    for idx in unique[plain_text][0]:
                        words[idx]["translation_cn"] = results[0]
                    translated_count += 1
                except Exception:
                    errors += 1
                    print(f"  [{words[unique[plain_text][0][0]].get('word', '?')}] translation failed",
                          file=sys.stderr)

        # Progress
        progress = min(batch_start + BATCH_SIZE, total)
        print(f"\r  {progress}/{total} sentences", end="", file=sys.stderr, flush=True)

    print(file=sys.stderr)

    # Write output
    output_path = args.output if args.output else json_path
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    char_count = sum(len(t[0]) for t in to_translate)
    print(f"Done: {translated_count} unique translated, {errors} failed, "
          f"~{char_count} chars used of 500,000 monthly quota",
          file=sys.stderr)


if __name__ == "__main__":
    main()
