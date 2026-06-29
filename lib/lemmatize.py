"""Inflectional lemmatization engine (屈折还原，拒绝跨词性转换).

Shared library that reduces English surface forms to their dictionary
base form using only inflectional morphology -- never crossing part-of-speech
boundaries.

Public API
----------
lemmatize(word, coca_set) -> str
    Comprehensive lemmatization (IRREG + regular patterns, COCA-validated).
    Used by vocab-list for full-book vocabulary extraction.

lemmatize_conservative(word) -> str
    Conservative VERB/NOUN-only lemmatization via lemminflect.
    Used by vocab-anki to avoid false positives in flashcard generation.
"""

from __future__ import annotations

# ============================================================================
# IRREGULAR FORM DICTIONARY (inflected -> base lemma)
# ============================================================================

IRREG: dict[str, str] = {
    # ── "be" ──
    "am": "be", "'m": "be", "is": "be", "'s": "be", "are": "be", "'re": "be",
    "was": "be", "were": "be", "been": "be", "being": "be",
    # ── "have" ──
    "has": "have", "had": "have", "having": "have",
    # ── "do" ──
    "does": "do", "did": "do", "doing": "do",
    # ── "go" ──
    "goes": "go", "went": "go", "gone": "go", "going": "go",
    # ── "say" ──
    "says": "say", "said": "say",

    # -- Irregular past -> base --
    "arose": "arise", "awoke": "awake", "bore": "bear",
    "beat": "beat", "became": "become", "began": "begin",
    "bent": "bend", "bit": "bite", "bled": "bleed", "blew": "blow",
    "broke": "break", "brought": "bring", "built": "build", "burnt": "burn",
    "bought": "buy", "caught": "catch", "chose": "choose", "came": "come",
    "crept": "creep", "dealt": "deal", "dug": "dig",
    "drew": "draw", "drank": "drink", "drove": "drive",
    "ate": "eat", "fell": "fall", "fed": "feed", "felt": "feel",
    "fought": "fight", "found": "find", "fled": "flee", "flew": "fly",
    "forgot": "forget", "forgave": "forgive", "forsook": "forsake",
    "froze": "freeze", "got": "get", "gave": "give",
    "grew": "grow", "hung": "hang", "heard": "hear",
    "hid": "hide", "held": "hold",
    "kept": "keep", "knelt": "kneel", "knew": "know", "laid": "lay",
    "led": "lead", "left": "leave", "lent": "lend",
    "lit": "light", "lost": "lose", "made": "make",
    "meant": "mean", "met": "meet", "paid": "pay",
    "rode": "ride", "rang": "ring", "rose": "rise", "ran": "run",
    "saw": "see", "sought": "seek", "sold": "sell", "sent": "send",
    "shook": "shake", "shone": "shine", "shot": "shoot",
    "sang": "sing", "sank": "sink", "sat": "sit",
    "slept": "sleep", "slid": "slide", "spoke": "speak", "sped": "speed",
    "spent": "spend", "spun": "spin", "sprang": "spring", "stood": "stand",
    "stole": "steal", "stuck": "stick", "struck": "strike", "swore": "swear",
    "swept": "sweep", "swam": "swim", "swung": "swing", "took": "take",
    "taught": "teach", "tore": "tear", "told": "tell", "thought": "think",
    "threw": "throw", "understood": "understand", "woke": "wake",
    "wore": "wear", "wept": "weep", "won": "win", "wound": "wind",
    "wrote": "write", "overcame": "overcome", "withdrew": "withdraw",
    "mistook": "mistake", "forbade": "forbid",

    # -- Past participles (different from past) --
    "borne": "bear", "beaten": "beat", "begun": "begin",
    "bitten": "bite", "blown": "blow", "broken": "break", "chosen": "choose",
    "done": "do", "drawn": "draw", "drunk": "drink", "driven": "drive",
    "eaten": "eat", "fallen": "fall", "flown": "fly", "forgotten": "forget",
    "forgiven": "forgive", "forsaken": "forsake", "frozen": "freeze",
    "given": "give", "grown": "grow", "hidden": "hide", "known": "know",
    "lain": "lie", "ridden": "ride", "rung": "ring", "risen": "rise",
    "seen": "see", "shaken": "shake", "sung": "sing", "sunk": "sink",
    "spoken": "speak", "sprung": "spring", "stolen": "steal",
    "stridden": "stride", "sworn": "swear", "swum": "swim", "taken": "take",
    "torn": "tear", "thrown": "throw", "woken": "wake", "worn": "wear",
    "withdrawn": "withdraw", "written": "write",

    # -- Gerunds with spelling changes --
    "dying": "die", "lying": "lie", "tying": "tie",

    # -- Contractions (without apostrophe, as they appear in cleaned text) --
    "cant": "can", "cannot": "can", "wont": "will", "dont": "do",
    "isnt": "be", "arent": "be", "wasnt": "be", "werent": "be",
    "hasnt": "have", "havent": "have", "hadnt": "have",
    "couldnt": "can", "wouldnt": "will", "shouldnt": "shall", "mustnt": "must",
    "didnt": "do", "doesnt": "do",

    # -- Irregular noun plurals --
    "men": "man", "women": "woman", "children": "child",
    "feet": "foot", "teeth": "tooth", "geese": "goose",
    "mice": "mouse", "lice": "louse", "oxen": "ox",
    "phenomena": "phenomenon", "crises": "crisis",

    # -- Irregular comparatives / superlatives --
    "better": "good", "best": "good",
    "worse": "bad", "worst": "bad",
    "more": "much", "most": "much",
    "less": "little", "least": "little",
    "further": "far", "furthest": "far", "farther": "far", "farthest": "far",
    "elder": "old", "eldest": "old",
}

# Additional learnt / poetic / archaic forms
IRREG.update({
    "leant": "lean", "leapt": "leap", "learnt": "learn",
    "spelt": "spell", "smelt": "smell", "dwelt": "dwell",
    "dreamt": "dream", "meant": "mean", "burnt": "burn",
    "cost": "cost", "cut": "cut", "hit": "hit", "hurt": "hurt",
    "let": "let", "put": "put", "set": "set", "shut": "shut",
    "spread": "spread", "split": "split", "thrust": "thrust",
    "bet": "bet", "burst": "burst", "cast": "cast",
    "read": "read", "shed": "shed", "wed": "wed",
})


# ============================================================================
# Derivational adjective detection (prevents cross-POS lemmatization)
# ============================================================================

# Words that lemminflect mis-analyses as verb participles but are actually
# derivational adjectives in context.  Without a POS tagger we can't reliably
# distinguish, so we maintain a small manual blocklist for common cases.
DERIVATIONAL_ADJ_BLOCKLIST: set[str] = {
    "blundering",   # derivational adj., not "blunder" v. participle
    "conceited",    # derivational adj., not "conceit" n./v. participle
}


def _is_derivational_adj(w: str) -> bool:
    """Check whether an -ing/-ed word is more likely a derivational adjective.

    Uses lemminflect: if the ADJ lemmatizer keeps the word unchanged while
    the VERB lemmatizer reduces it, the word is probably a true adjective
    (e.g. *interesting*, *boring*) rather than a verb participle.
    """
    if w in DERIVATIONAL_ADJ_BLOCKLIST:
        return True
    try:
        from lemminflect import getLemma  # noqa: F811
    except ImportError:
        return False
    adj = getLemma(w, "ADJ")
    verb = getLemma(w, "VERB")
    adj_unchanged = adj and all(a == w for a in adj)
    verb_changes = verb and any(v != w for v in verb)
    return adj_unchanged and verb_changes


# ============================================================================
# Regular inflectional pattern helpers (internal)
# ============================================================================

def _try_ing(w: str, coca_set: set[str]) -> list[str]:
    """-ing forms: walking->walk, making->make, running->run, sitting->sit."""
    if not w.endswith("ing") or len(w) <= 4:
        return []
    if _is_derivational_adj(w):
        return []
    base = w[:-3]  # walk, mak, runn, sitt
    results: list[str] = []
    # plain (walking->walk)
    if base in coca_set:
        results.append(base)
    # dropped-e (making->make)
    if (base + "e") in coca_set:
        results.append(base + "e")
    # doubled consonant (running->run, sitting->sit)
    if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
        single = base[:-1]
        if single in coca_set:
            results.append(single)
    return results


def _try_ed(w: str, coca_set: set[str]) -> list[str]:
    """-ed forms: walked->walk, loved->love, stopped->stop, cried->cry."""
    if not w.endswith("ed") or len(w) <= 3:
        return []
    if _is_derivational_adj(w):
        return []
    results: list[str] = []
    # -ied -> -y (cried->cry)
    if w.endswith("ied") and len(w) > 4:
        cand = w[:-3] + "y"
        if cand in coca_set:
            results.append(cand)
    base = w[:-2]  # walk, lov, stopp
    if base in coca_set:
        results.append(base)
    if (base + "e") in coca_set:
        results.append(base + "e")
    if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
        single = base[:-1]
        if single in coca_set:
            results.append(single)
    return results


def _try_s_es(w: str, coca_set: set[str]) -> list[str]:
    """Plural nouns / 3sg verbs: cats->cat, kisses->kiss, babies->baby."""
    if not w.endswith("s") or len(w) <= 2:
        return []
    results: list[str] = []
    # -ies -> -y (babies->baby, flies->fly)
    if w.endswith("ies") and len(w) > 4:
        cand = w[:-3] + "y"
        if cand in coca_set:
            results.append(cand)
    # -ses/-shes/-ches/-xes/-zes -> strip -es (kisses->kiss)
    for sfx in ("ses", "shes", "ches", "xes", "zes"):
        if w.endswith(sfx) and len(w) > 4:
            cand = w[:-2]
            if cand in coca_set:
                results.append(cand)
    # plain -s (cats->cat)
    cand = w[:-1]
    if cand in coca_set and len(cand) >= 2:
        results.append(cand)
    # -ves -> -f/-fe (knives->knife, wolves->wolf)
    if w.endswith("ves") and len(w) > 4:
        for sfx in ("f", "fe"):
            cand = w[:-3] + sfx
            if cand in coca_set:
                results.append(cand)
    return results


def _try_er(w: str, coca_set: set[str]) -> list[str]:
    """Comparative -er: bigger->big, smaller->small, happier->happy."""
    if not w.endswith("er") or len(w) <= 3:
        return []
    results: list[str] = []
    if w.endswith("ier") and len(w) > 4:
        cand = w[:-3] + "y"
        if cand in coca_set:
            results.append(cand)
    base = w[:-2]
    if base in coca_set:
        results.append(base)
    if (base + "e") in coca_set:
        results.append(base + "e")
    if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
        single = base[:-1]
        if single in coca_set:
            results.append(single)
    return results


def _try_est(w: str, coca_set: set[str]) -> list[str]:
    """Superlative -est: biggest->big, smallest->small, happiest->happy."""
    if not w.endswith("est") or len(w) <= 4:
        return []
    results: list[str] = []
    if w.endswith("iest") and len(w) > 5:
        cand = w[:-4] + "y"
        if cand in coca_set:
            results.append(cand)
    base = w[:-3]
    if base in coca_set:
        results.append(base)
    if (base + "e") in coca_set:
        results.append(base + "e")
    if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiouy":
        single = base[:-1]
        if single in coca_set:
            results.append(single)
    return results


# ============================================================================
# Public API
# ============================================================================

def lemmatize(word: str, coca_set: set[str]) -> str:
    """Comprehensive inflectional lemmatization with COCA validation.

    Strategy
    --------
    1. If *word* is already in COCA -> return it unchanged.
    2. Try IRREG dict -> if result is in COCA, use it (absolute priority).
    3. Try regular inflectional patterns -> pick the shortest COCA-valid result.
    4. Otherwise return the original word.

    *No cross-POS conversion*: derivational adjectives like *blundering*
    stay as-is because the -ing -> VERB path is only taken when the
    resulting lemma is in COCA and no competing analysis blocks it.
    """
    w = word.lower()

    # 1. Already in COCA -- keep as-is (no unnecessary lemmatisation)
    if w in coca_set:
        return w

    # 2. IRREG check (highest priority)
    if w in IRREG:
        lemma = IRREG[w]
        if lemma in coca_set:
            return lemma

    # 3. Regular patterns (result must be in COCA)
    reg_candidates: list[str] = []
    reg_candidates.extend(_try_ing(w, coca_set))
    reg_candidates.extend(_try_ed(w, coca_set))
    reg_candidates.extend(_try_s_es(w, coca_set))
    reg_candidates.extend(_try_er(w, coca_set))
    reg_candidates.extend(_try_est(w, coca_set))

    # Possessive -'s
    if w.endswith("'s") and len(w) > 3:
        cand = w[:-2]
        if cand in coca_set:
            reg_candidates.append(cand)

    if reg_candidates:
        # Prefer shortest valid candidate (inflectional reduction)
        best = min(reg_candidates, key=lambda x: (len(x), x))
        return best

    # 4. No lemmatisation possible
    return w


def lemmatize_conservative(word: str) -> str:
    """Conservative VERB/NOUN-only lemmatization via lemminflect.

    Only accepts a lemma that is *strictly shorter* than the input word.
    This avoids cross-POS false positives (abode n. -> abide v.) and is
    suitable for flashcard generation where precision matters more than recall.
    """
    try:
        from lemminflect import getLemma
    except ImportError:
        return word.lower()

    w = word.lower()
    candidates: list[str] = []

    for upos in ("VERB", "NOUN"):
        lemmas = getLemma(w, upos)
        if not lemmas:
            continue
        for lemma in lemmas:
            if lemma != w and len(lemma) < len(w):
                candidates.append(lemma)

    if candidates:
        return min(candidates, key=lambda x: (len(x), x))
    return w
