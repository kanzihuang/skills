"""Audit an Anki deck for card quality issues.

Uses lemmatize_word() from the project's own utils — no hand-rolled
reduction rules.  For each card, compares the stored Word (lemma) against
the surface form in <b> tags.

Checks:
  1. Word ≠ lemmatize_word(<b> text) AND Word ≠ <b> text
     → lemma is neither the mechanical reduction NOR a deliberate adj override
  2. Missing IPA / definition / translation
  3. Sentence > 150 chars (with tags)

Usage:
  python scripts/audit_deck.py "小王子（英文版） (圣埃克絮佩里)"
"""

import json
import re
import sys
import urllib.request

# Allow running from repo root or vocab-anki/
import os
_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _skill_dir not in sys.path:
    sys.path.insert(0, _skill_dir)

from utils import lemmatize_word

ANKICONNECT = "http://localhost:8765"


def _ankiconnect(action: str, **params) -> dict:
    req = json.dumps({"action": action, "version": 6, "params": params})
    with urllib.request.urlopen(ANKICONNECT, req.encode(), timeout=30) as resp:
        return json.loads(resp.read())


def audit_deck(deck_name: str) -> dict:
    """Run audit and return results dict."""

    # 1. Find all notes in the deck
    note_ids = _ankiconnect("findNotes", query=f'deck:"{deck_name}"')["result"]
    if not note_ids:
        print(f"No cards found in deck: {deck_name}")
        return {}

    # 2. Fetch note details in batches
    all_notes = []
    for i in range(0, len(note_ids), 100):
        batch = note_ids[i : i + 100]
        all_notes.extend(
            _ankiconnect("notesInfo", notes=batch)["result"]
        )

    # 3. Classify each card
    lemma_mismatches = []
    missing_ipa = []
    missing_def = []
    missing_trans = []
    too_long = []

    for n in all_notes:
        f = n["fields"]
        word = f.get("Word", {}).get("value", "").strip()
        sentence = f.get("Sentence", {}).get("value", "").strip()
        ipa = f.get("IPA", {}).get("value", "").strip()
        definition = f.get("DefinitionCN", {}).get("value", "").strip()
        translation = f.get("TranslationCN", {}).get("value", "").strip()

        # Skip meta card
        if word == "__META__":
            continue

        # Extract <b> text
        m = re.search(r"<b>(.*?)</b>", sentence)
        if not m:
            continue  # no <b> tag — can't audit
        b_text = m.group(1)

        # Core check: is Word a legitimate lemma for the surface form?
        # Valid if Word == lemmatize_word(b_text)  (mechanical reduction)
        # OR Word == b_text  (explicit adj override, e.g. blundering→blundering)
        mechanical = lemmatize_word(b_text)
        if word.lower() != mechanical.lower() and word.lower() != b_text.lower():
            lemma_mismatches.append({
                "word": word,
                "b_text": b_text,
                "lemmatized": mechanical,
                "sentence": sentence[:120],
            })

        # Field presence
        if not ipa:
            missing_ipa.append(word)
        if len(definition) < 2:
            missing_def.append(word)
        if not translation:
            missing_trans.append(word)

        # Sentence length (with tags, as sync_anki.py validates)
        if len(sentence) > 150:
            too_long.append((word, len(sentence)))

    # 4. Report
    total = len(all_notes) - 1  # exclude meta
    print(f"Deck: {deck_name}")
    print(f"Cards: {total}")
    print()

    if lemma_mismatches:
        print(f"--- Word ≠ lemmatize(<b>) AND Word ≠ <b> ({len(lemma_mismatches)}) ---")
        for item in lemma_mismatches:
            print(f"  Word='{item['word']}'  <b>='{item['b_text']}'  "
                  f"lemmatize→'{item['lemmatized']}'")
            print(f"    {item['sentence']}")
    else:
        print("Word / <b> consistency: ✅")

    if missing_ipa:
        print(f"\nMissing IPA ({len(missing_ipa)}): {', '.join(missing_ipa[:10])}")
    else:
        print("IPA: ✅")

    if missing_def:
        print(f"Missing definition ({len(missing_def)}): {', '.join(missing_def[:10])}")
    else:
        print("Definitions: ✅")

    if missing_trans:
        print(f"Missing translation ({len(missing_trans)}): {', '.join(missing_trans[:10])}")
    else:
        print("Translations: ✅")

    if too_long:
        print(f"\nSentence > 150 chars ({len(too_long)}):")
        for w, l in too_long:
            print(f"  {w}: {l} chars")
    else:
        print("Sentence length: ✅")

    print(f"\n{'═' * 40}")
    issues = len(lemma_mismatches) + len(missing_ipa) + len(missing_def) + len(too_long)
    print(f"{'✅ All clear!' if issues == 0 else f'❌ {issues} issue(s) found'}")
    print(f"{'═' * 40}")

    return {
        "total": total,
        "lemma_mismatches": lemma_mismatches,
        "missing_ipa": missing_ipa,
        "missing_def": missing_def,
        "missing_trans": missing_trans,
        "too_long": too_long,
    }


if __name__ == "__main__":
    deck = sys.argv[1] if len(sys.argv) > 1 else "小王子（英文版） (圣埃克絮佩里)"
    audit_deck(deck)
