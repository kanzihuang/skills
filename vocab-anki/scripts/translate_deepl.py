#!/usr/bin/env python3
"""Translate sentences via DeepL API.

Reads a vocab-anki JSON file, strips <b> tags from sentences, translates
them via DeepL, and writes the translations back into the JSON.

Usage:
    python scripts/translate_deepl.py /tmp/vocab-anki-input-xxx.json

Requires DEEPL_API_KEY environment variable (free key from deepl.com/pro-api).
Free tier: 500,000 chars/month, api-free.deepl.com endpoint.

DeepL does not support <b> tags natively. We strip them before sending,
then DeepL's output naturally includes the word in translation context.
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "")
if not DEEPL_API_KEY:
    print("ERROR: DEEPL_API_KEY environment variable not set.", file=sys.stderr)
    sys.exit(1)

# Free tier uses api-free.deepl.com
DEEPL_URL = "https://api-free.deepl.com/v2/translate"


def strip_tags(text: str) -> str:
    """Remove <b> markup, keeping the inner text."""
    return re.sub(r"</?b>", "", text)


def translate_batch(texts: list[str]) -> list[str]:
    """Translate a batch of texts via DeepL API. Returns translations in order."""
    body = json.dumps({
        "text": texts,
        "target_lang": "ZH",
    }).encode("utf-8")

    req = urllib.request.Request(
        DEEPL_URL,
        data=body,
        headers={
            "Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return [t["text"] for t in result["translations"]]
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"  DeepL HTTP {e.code}: {body_text[:200]}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"  DeepL error: {e}", file=sys.stderr)
        raise


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not json_path or not os.path.exists(json_path):
        print(f"Usage: {sys.argv[0]} <vocab-anki-input.json>", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    words = data.get("words", [])
    if not words:
        print("No words to translate.", file=sys.stderr)
        return

    # Collect sentences (without <b> tags) and track which need translation
    to_translate: list[tuple[int, str]] = []  # (index, plain_text)
    for i, w in enumerate(words):
        sentence = w.get("sentence", "")
        current_trans = w.get("translation_cn", "").strip()
        plain = strip_tags(sentence).strip()
        if plain:
            to_translate.append((i, plain))

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
        texts = [t[1] for t in batch]
        indices = [t[0] for t in batch]

        try:
            translations = translate_batch(texts)
            for j, (idx, _) in enumerate(batch):
                words[idx]["translation_cn"] = translations[j]
                translated_count += 1
        except Exception:
            errors += 1
            print(f"  Batch {batch_start // BATCH_SIZE + 1} failed, retrying individually...",
                  file=sys.stderr)
            # Fall back to individual translation
            for (idx, plain_text) in batch:
                try:
                    results = translate_batch([plain_text])
                    words[idx]["translation_cn"] = results[0]
                    translated_count += 1
                except Exception:
                    errors += 1
                    print(f"  [{words[idx].get('word', '?')}] translation failed",
                          file=sys.stderr)

        # Progress
        progress = min(batch_start + BATCH_SIZE, total)
        print(f"\r  {progress}/{total} sentences", end="", file=sys.stderr, flush=True)

        # Rate limiting: free tier has no strict rate limit but be polite
        if batch_start + BATCH_SIZE < total:
            time.sleep(0.2)

    print(file=sys.stderr)

    # Write back
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    char_count = sum(len(t[1]) for t in to_translate)
    print(f"Done: {translated_count} translated, {errors} failed, "
          f"~{char_count} chars used of 500,000 monthly quota",
          file=sys.stderr)


if __name__ == "__main__":
    main()
