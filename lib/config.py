"""Centralized configuration constants shared across lib/ modules.

All magic numbers and hardcoded values that appear in multiple files
live here, so tuning a value only requires one edit.
"""

# ── Edge TTS (audio synthesis) ──────────────────────────────────────────────
EDGE_TTS_MAX_RETRIES = 2       # extra attempts on transient failure (3 total)
EDGE_TTS_RETRY_DELAY = 0.75    # seconds between retries

# ── sync_anki.py ────────────────────────────────────────────────────────────
MAX_SENTENCE_LENGTH = 250      # chars — sentences longer than this must be
                                # truncated by Step 2B before reaching sync
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
MAX_CANDIDATES = 5             # max sentence candidates per word
HARD_CUTOFF = 500              # chars — mechanical cutoff before semantic truncation

# ── translate_deepl.py ──────────────────────────────────────────────────────
BATCH_SIZE = 50                # DeepL batch translation size
CONTEXT_SENTENCES = 2          # source sentences before/after target for context
