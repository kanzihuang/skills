"""Audit an Anki deck for card quality issues.

Uses lemmatize_word() from the project's own utils — no hand-rolled
reduction rules.  For each card, compares the stored Word (lemma) against
the surface form in <b> tags.

Checks:
  1. Word ≠ lemmatize_word(<b> text) AND Word ≠ <b> text
     → lemma is neither the mechanical reduction NOR a deliberate adj override
  2. Missing IPA / definition / translation

Usage:
  python scripts/audit_deck.py "Deck Name (Author)"
"""

import json
import re
import sys
import urllib.request

# Add repo root to sys.path so lib.* imports work when run as a script
import os
_script_dir = os.path.dirname(os.path.abspath(__file__))      # lib/scripts/
_package_dir = os.path.dirname(_script_dir)                    # lib/
_repo_root = os.path.dirname(_package_dir)                     # skills/
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from lib.sync_anki import resolve_lemma
from lib.utils import lemmatize_word

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
    meta_count = 0

    for n in all_notes:
        f = n["fields"]
        word = f.get("Word", {}).get("value", "").strip()
        sentence = f.get("Sentence", {}).get("value", "").strip()
        ipa = f.get("IPA", {}).get("value", "").strip()
        definition = f.get("DefinitionCN", {}).get("value", "").strip()
        translation = f.get("TranslationCN", {}).get("value", "").strip()

        # Skip meta card
        if word == "__META__":
            meta_count += 1
            continue

        # Extract <b> text
        m = re.search(r"<b>(.*?)</b>", sentence)
        if not m:
            continue  # no <b> tag — can't audit
        b_text = m.group(1)

        # Core check: is Word a legitimate lemma for the surface form?
        # Uses resolve_lemma() which trusts explicit Claude overrides
        # for documented lemmatize_word limitations (same-length irregulars,
        # derivational adjectives).
        expected = resolve_lemma(b_text, word)  # word as explicit override
        mechanical = lemmatize_word(b_text)
        if word.lower() != expected.lower() and word.lower() != b_text.lower():
            lemma_mismatches.append({
                "word": word,
                "b_text": b_text,
                "lemmatized": mechanical,
                "expected": expected,
                "sentence": sentence[:120],
            })

        # Field presence
        if not ipa:
            missing_ipa.append(word)
        if len(definition) < 2:
            missing_def.append(word)
        if not translation:
            missing_trans.append(word)

    # 4. Report
    total = len(all_notes) - meta_count
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

    print(f"\n{'═' * 40}")
    issues = len(lemma_mismatches) + len(missing_ipa) + len(missing_def)
    print(f"{'✅ All clear!' if issues == 0 else f'❌ {issues} issue(s) found'}")
    print(f"{'═' * 40}")

    return {
        "total": total,
        "lemma_mismatches": lemma_mismatches,
        "missing_ipa": missing_ipa,
        "missing_def": missing_def,
        "missing_trans": missing_trans,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <deck_name>", file=sys.stderr)
        print("  deck_name : Anki deck name (e.g. 'The Little Prince (Author)')", file=sys.stderr)
        sys.exit(1)
    audit_deck(sys.argv[1])
