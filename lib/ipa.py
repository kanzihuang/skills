"""CMU Pronouncing Dictionary → IPA conversion.

Loads the 135K-entry cmudict, converts ARPAbet phonemes to IPA with
stress placement following the Maximal Onset Principle.

Exported:
  _load_cmudict()       — load cmudict (cached)
  _cmu_ipa(word)        — IPA lookup with heteronym disambiguation
  _arpabet_to_ipa()     — single-phoneme conversion
"""

from __future__ import annotations

# ── cmudict cache ────────────────────────────────────────────────────────────

_CMUDICT: dict[str, list[list[str]]] | None = None


def _load_cmudict() -> dict[str, list[list[str]]]:
    """Load CMU Pronouncing Dictionary (cached)."""
    global _CMUDICT
    if _CMUDICT is not None:
        return _CMUDICT
    _CMUDICT = {}
    try:
        from pathlib import Path
        path = (
            Path(__file__).resolve().parent
            / "data" / "cmudict.dict"
        )
        if not path.exists():
            return _CMUDICT
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(";;;"):
                    continue
                parts = line.split()
                word = parts[0].lower().rstrip(")").split("(")[0]
                phones = parts[1:]
                if word not in _CMUDICT:
                    _CMUDICT[word] = []
                _CMUDICT[word].append(phones)
    except Exception:
        pass
    return _CMUDICT


# ── ARPAbet → IPA phoneme map ────────────────────────────────────────────────

_ARPABET_TO_IPA = {
    "AA": "ɑː", "AE": "æ",  "AH": "ʌ",  "AO": "ɔː", "AW": "aʊ",
    "AY": "aɪ", "EH": "e",  "ER": "ɜːr","EY": "eɪ", "IH": "ɪ",
    "IY": "iː", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ",  "UW": "uː",
    "B": "b",   "CH": "tʃ", "D": "d",   "DH": "ð",  "F": "f",
    "G": "ɡ",   "HH": "h",  "JH": "dʒ","K": "k",   "L": "l",
    "M": "m",   "N": "n",   "NG": "ŋ",  "P": "p",   "R": "r",
    "S": "s",   "SH": "ʃ",  "T": "t",   "TH": "θ",  "V": "v",
    "W": "w",   "Y": "j",   "Z": "z",   "ZH": "ʒ",
}

# Legal English onset consonant clusters (ARPAbet phonemes).
_SONORANTS = frozenset({"L", "R", "W", "Y"})
_OBSTRUENTS = frozenset({
    "P", "B", "T", "D", "K", "G",
    "F", "V", "TH", "DH", "S", "Z",
    "SH", "ZH", "CH", "JH", "HH",
})


def _is_legal_onset(consonants: list[str]) -> bool:
    """Check whether a sequence of ARPAbet consonants is a legal English onset."""
    n = len(consonants)
    if n == 0:
        return True
    if n == 1:
        return consonants[0] != "NG"
    if n == 2:
        c1, c2 = consonants
        if c1 in _OBSTRUENTS and c2 in _SONORANTS:
            return True
        if c1 == "S" and c2 in ("P", "T", "K"):
            return True
        if c1 == "S" and c2 in ("M", "N"):
            return True
        return False
    if n == 3:
        c1, c2, c3 = consonants
        if c1 == "S" and c2 in ("P", "T", "K") and c3 in _SONORANTS:
            return True
        return False
    return False


def _arpabet_to_ipa(arpa: str, stress_digit: str = "") -> str:
    """Convert a single ARPAbet phoneme to IPA, handling special cases.

    *stress_digit* is the original CMU stress marker ("" , "0", "1", "2").
    ER0 (unstressed) → /ər/;  ER1/ER2 (stressed) → /ɜːr/.
    AH0 (unstressed) → /ə/;  AH1/AH2 (stressed) → /ʌ/.
    """
    if arpa == "ER":
        return "ər" if stress_digit == "0" else "ɜːr"
    if arpa == "AH":
        return "ə" if stress_digit == "0" else "ʌ"
    return _ARPABET_TO_IPA.get(arpa, arpa.lower())


def _pick_best_pronunciation(
    entries: list[list[str]], claude_ipa: str
) -> list[str]:
    """Pick the cmudict entry closest to Claude's IPA by vowel match."""
    claude_vowels = set()
    for ch in claude_ipa.strip("/"):
        if ch in "iɪeæɑɔoʊuʌəɜa":
            claude_vowels.add(ch)

    def score(phones: list[str]) -> int:
        s = 0
        for p in phones:
            base = p.rstrip("012")
            mapped = _ARPABET_TO_IPA.get(base, "")
            for ch in mapped:
                if ch in claude_vowels:
                    s += 1
            if p[-1].isdigit() and "ˈ" in claude_ipa and p.endswith("1"):
                s += 1
        return s

    best = max(entries, key=score)
    return best


def _cmu_ipa(word: str, claude_ipa: str = "") -> str | None:
    """Look up IPA for *word* in cmudict.  Returns None if not found.

    For multi-pronunciation words, *claude_ipa* is used as a tiebreaker
    to pick the phonetically closest entry (handles heteronyms like
    read/read, wound/wound).  Without a Claude IPA, defaults to the
    first entry.

    Stress placement follows the Maximal Onset Principle: consonants
    between vowels are assigned to the following syllable's onset when
    they form a legal English onset cluster.
    """
    cmu = _load_cmudict()
    w = word.lower()
    if w not in cmu:
        return None
    entries = cmu[w]
    if len(entries) == 1 or not claude_ipa:
        phones = entries[0]
    else:
        phones = _pick_best_pronunciation(entries, claude_ipa)

    # ── Two-pass ARPAbet → IPA conversion ──────────────────────────
    segments: list[tuple[str, bool, str]] = []
    for p in phones:
        if p[-1].isdigit():
            segments.append((p[:-1], True, p[-1]))
        else:
            segments.append((p, False, ""))

    vowel_count = sum(1 for _, is_v, _ in segments if is_v)

    result: list[str] = []
    pending: list[str] = []

    for arpa, is_vowel, stress_digit in segments:
        if is_vowel:
            stress_mark = ""
            if stress_digit == "1" and vowel_count > 1:
                stress_mark = "ˈ"
            elif stress_digit == "2" and vowel_count > 1:
                stress_mark = "ˌ"

            onset_size = 0
            if pending:
                for n in range(min(len(pending), 3), 0, -1):
                    if _is_legal_onset(pending[-n:]):
                        onset_size = n
                        break

            coda_count = len(pending) - onset_size
            for c in pending[:coda_count]:
                result.append(_arpabet_to_ipa(c))
            if stress_mark:
                result.append(stress_mark)
            for c in pending[coda_count:]:
                result.append(_arpabet_to_ipa(c))
            pending = []
            result.append(_arpabet_to_ipa(arpa, stress_digit))
        else:
            pending.append(arpa)

    for c in pending:
        result.append(_arpabet_to_ipa(c))

    return "/" + "".join(result) + "/"
