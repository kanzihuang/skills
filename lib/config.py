"""Centralized configuration constants shared across lib/ modules.

All magic numbers and hardcoded values that appear in multiple files
live here, so tuning a value only requires one edit.
"""

# ── Edge TTS (audio synthesis) ──────────────────────────────────────────────
EDGE_TTS_MAX_RETRIES = 2       # extra attempts on transient failure (3 total)
EDGE_TTS_RETRY_DELAY = 0.75    # seconds between retries

# ── sync_anki.py ────────────────────────────────────────────────────────────
MAX_SENTENCE_LENGTH = 400      # chars — smart_truncate tries to shorten
                                # sentences exceeding this; validation.py warns
                                # when the limit is exceeded
MIN_SENTENCE_LENGTH = 30       # chars — match_sentences.py prefers candidates
                                # ≥ this length; validation.py warns when the
                                # final sentence falls below it. Based on data:
                                # 30-char sentences like "'Good morning,' he
                                # said courteously." already provide sufficient
                                # context. Only <30 (e.g. "She hesitated.") is
                                # truly insufficient.

# ── AnkiConnect ─────────────────────────────────────────────────────────────
ANKICONNECT_URL = "http://localhost:8765"
ANKICONNECT_VERSION = 6
REQUEST_TIMEOUT = 10           # seconds per HTTP request

# ── match_sentences.py ──────────────────────────────────────────────────────
HARD_CUTOFF = 500              # chars — mechanical cutoff before semantic truncation

# ── smart_truncate() / validate_word_entries() ──────────────────────────────
# Words that indicate a truncated fragment when found at the end of a
# sentence.  Used by smart_truncate() to avoid ending on a function word,
# and by validate_word_entries() to flag likely truncated fragments.
SENTENCE_END_FUNCTION_WORDS: frozenset[str] = frozenset({
    "from", "with", "at", "for", "to", "of", "in", "on", "by",
    "about", "into", "onto", "upon", "within", "without", "through",
    "across", "along", "around", "before", "after", "between",
    "among", "during", "until", "against", "toward", "towards",
    "over", "under", "behind", "beside", "beneath",
    "and", "but", "or", "nor", "so", "yet", "because",
    "although", "though", "while", "when", "where",
    "since", "if", "unless", "as",
    "had", "has", "was", "were", "could", "would", "should",
    "also", "even", "just", "still", "then", "now", "only",
    "quite", "rather", "almost", "very", "too", "already",
    "always", "never", "often", "here", "there", "again",
    "once", "soon", "ever", "indeed", "hardly", "merely",
    "nearly", "else",
    # Determiners — never valid as standalone sentence endings:
    "the", "a", "an",
    # Possessive determiners (NOT pronoun-capable; "his" is excluded
    # because it can be a nominal possessive pronoun: "It is his."):
    "its", "her", "their", "our", "your", "my",
})

# ── translate_deepl.py ──────────────────────────────────────────────────────
BATCH_SIZE = 50                # DeepL batch translation size
CONTEXT_SENTENCES = 2          # source sentences before/after target for context
