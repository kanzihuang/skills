"""AnkiConnect API client for interacting with a running Anki instance.

AnkiConnect is a local HTTP API plugin for Anki desktop. It exposes an
endpoint at http://localhost:8765 and allows programmatic access to create
decks, add notes, store media files, and query existing cards — all while
preserving review history for cards that already exist.

Usage:
    from ankiconnect import AnkiConnect

    ac = AnkiConnect()
    decks = ac.list_decks()
    notes = ac.find_notes_in_deck("My Deck Name")
"""

import base64
import json
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AnkiConnect client
# ---------------------------------------------------------------------------

from .config import ANKICONNECT_URL, ANKICONNECT_VERSION, REQUEST_TIMEOUT


class AnkiConnectError(Exception):
    """Raised when AnkiConnect returns an error or is unreachable."""


class AnkiConnect:
    """Thin wrapper around the AnkiConnect JSON-RPC API."""

    def __init__(self, url: str = ANKICONNECT_URL) -> None:
        self.url = url

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def version(self) -> str:
        """Return AnkiConnect API version. Lightweight connectivity check."""
        return self._call("version")

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    def _call(self, action: str, **params: Any) -> Any:
        """Make an AnkiConnect call with one retry on connection failure.

        Raises AnkiConnectError if both the initial attempt and the retry fail.
        """
        payload = {
            "action": action,
            "version": ANKICONNECT_VERSION,
            "params": params,
        }
        last_error = None
        for attempt in (1, 2):
            try:
                resp = requests.post(self.url, json=payload, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
            except requests.ConnectionError:
                last_error = AnkiConnectError(
                    "Cannot reach AnkiConnect after retry. "
                    "Is Anki running with the AnkiConnect plugin installed? (http://localhost:8765)"
                )
                if attempt == 2:
                    raise last_error
                time.sleep(2)
                continue
            except requests.RequestException as e:
                raise AnkiConnectError(f"AnkiConnect request failed: {e}")
            # Success — break out of retry loop
            break

        data = resp.json()
        error = data.get("error")
        if error:
            raise AnkiConnectError(f"AnkiConnect error: {error}")
        return data.get("result")

    # ------------------------------------------------------------------
    # Deck operations
    # ------------------------------------------------------------------

    def list_decks(self) -> list[str]:
        """Return all deck names in the collection."""
        return self._call("deckNames")

    def deck_names_and_ids(self) -> dict[str, int]:
        """Return {deck_name: deck_id} mapping."""
        return self._call("deckNamesAndIds")

    def create_deck(self, name: str) -> int:
        """Create a new deck. Returns the deck ID. Idempotent."""
        return self._call("createDeck", deck=name)

    # ------------------------------------------------------------------
    # Note queries
    # ------------------------------------------------------------------

    def find_notes(self, query: str) -> list[int]:
        """Find note IDs matching a search query.

        Examples:
            "deck:My Deck Name"
            "deck:English Word:example"
        """
        return self._call("findNotes", query=query)

    def notes_info(self, note_ids: list[int]) -> list[dict]:
        """Return full note info (fields, model, tags, cards, etc.)."""
        return self._call("notesInfo", notes=note_ids)

    # ------------------------------------------------------------------
    # Note mutations
    # ------------------------------------------------------------------

    def add_notes(self, notes: list[dict]) -> list[int | None]:
        """Add notes to the collection. Returns list of note IDs (None for dupes).

        Each note dict:
            {
                "deckName": "My Deck",
                "modelName": "Vocabulary Card (WeRead)",
                "fields": {
                    "Word": "pondered",
                    "Sentence": "I <b>pondered</b> deeply...",
                    ...
                },
                "tags": ["weread"],
                "audio": [{"url": "http://...", "filename": "pondered_word.mp3",
                           "fields": ["WordAudio"]}],
            }

        AnkiConnect supports inline audio via base64 data URLs or local
        file references. Media files should be uploaded separately via
        store_media_file() first, then referenced as [sound:filename.mp3].

        When the batch call fails because some notes are duplicates,
        AnkiConnect may return an array of per-note errors instead of
        a result list.  We catch that case and retry each note individually
        to get accurate per-note results.
        """
        try:
            return self._call("addNotes", notes=notes)
        except AnkiConnectError as e:
            errmsg = str(e)
            if "duplicate" in errmsg.lower():
                # Batch failed — some notes may be duplicates.
                # Retry individually to distinguish real dupes from
                # notes rejected only because of the batch failure.
                results: list[int | None] = []
                for note in notes:
                    try:
                        note_id = self._call("addNote", note=note)
                        results.append(note_id)
                    except AnkiConnectError:
                        results.append(None)
                return results
            raise

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        """Update fields of an existing note (preserves scheduling)."""
        return self._call(
            "updateNoteFields",
            note={"id": note_id, "fields": fields},
        )

    def can_add_notes(self, notes: list[dict]) -> list[bool]:
        """Check which notes would be added as new vs treated as dupes."""
        return self._call("canAddNotes", notes=notes)

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def store_media_file(self, filename: str, data: bytes) -> str | None:
        """Store a media file in Anki's media collection.

        Args:
            filename: Desired filename (e.g., "pondered_word.mp3")
            data: Raw binary content of the file

        Returns the stored filename on success, None on failure.
        """
        b64_data = base64.b64encode(data).decode("ascii")
        result = self._call(
            "storeMediaFile",
            filename=filename,
            data=b64_data,
        )
        return result

    def store_media_files_batch(
        self, files: list[tuple[str, bytes]], batch_size: int = 20
    ) -> list[str | None]:
        """Store multiple media files via AnkiConnect multi actions.

        Args:
            files: List of (filename, data) tuples.
            batch_size: Max actions per AnkiConnect multi request.

        Returns a flat list of stored filenames (None for failures).
        """
        all_results: list[str | None] = []
        for batch_start in range(0, len(files), batch_size):
            batch = files[batch_start:batch_start + batch_size]
            actions = [
                {
                    "action": "storeMediaFile",
                    "params": {
                        "filename": name,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
                for name, data in batch
            ]
            results = self._call("multi", actions=actions)
            if isinstance(results, list):
                all_results.extend(results)
            else:
                all_results.extend([None] * len(batch))
        return all_results

    def store_media_file_from_path(self, filepath: str) -> str | None:
        """Store a media file from a local file path."""
        with open(filepath, "rb") as f:
            data = f.read()
        import os

        filename = os.path.basename(filepath)
        return self.store_media_file(filename, data)

    # ------------------------------------------------------------------
    # Model operations
    # ------------------------------------------------------------------

    def list_models(self) -> list[str]:
        """Return all model names."""
        return self._call("modelNames")

    def model_styling(self, model_name: str) -> dict:
        """Return the CSS styling for a model."""
        return self._call("modelStyling", modelName=model_name)

    # ------------------------------------------------------------------
    # Higher-level helpers for vocab-anki workflow
    # ------------------------------------------------------------------

    def find_notes_in_deck(self, deck_name: str) -> list[int]:
        """Find all note IDs in a specific deck."""
        return self.find_notes(f'deck:"{deck_name}"')

    def get_word_map(self, deck_name: str) -> dict[str, int]:
        """Return {word_lowercase: note_id} for all notes in a deck.

        Uses the 'Word' field. If the deck doesn't exist or has no notes,
        returns an empty dict.
        """
        note_ids = self.find_notes_in_deck(deck_name)
        if not note_ids:
            return {}

        info = self.notes_info(note_ids)
        word_map: dict[str, int] = {}
        for n in info:
            fields = n.get("fields", {})
            word_field = fields.get("Word", {})
            word_value = word_field.get("value", "").strip().lower()
            if word_value:
                word_map[word_value] = n["noteId"]
        return word_map

    def get_word_id_map(self, deck_name: str) -> dict[str, int]:
        """Return {WordId: note_id} for all notes in a deck.

        Uses the 'WordId' field (composite key like 'pondered_22720170').
        If the deck doesn't exist or has no notes, returns an empty dict.
        """
        note_ids = self.find_notes_in_deck(deck_name)
        if not note_ids:
            return {}

        info = self.notes_info(note_ids)
        word_id_map: dict[str, int] = {}
        for n in info:
            fields = n.get("fields", {})
            val = fields.get("WordId", {}).get("value", "").strip()
            if val:
                word_id_map[val] = n["noteId"]
        return word_id_map

    def suspend_cards(self, card_ids: list[int]) -> bool:
        """Suspend cards by their IDs. Returns True on success."""
        return self._call("suspend", cards=card_ids)

    def get_cards_of_notes(self, note_ids: list[int]) -> list[int]:
        """Get card IDs for given note IDs."""
        return self._call("findCards", query=" or ".join(f"nid:{nid}" for nid in note_ids))

    def find_notes_by_field(self, deck_name: str, field_name: str, value: str) -> list[int]:
        """Find notes matching a specific field value, optionally scoped to a deck."""
        if deck_name:
            return self.find_notes(f'deck:"{deck_name}" {field_name}:{value}')
        return self.find_notes(f'{field_name}:{value}')

    def update_note_tags(self, note_id: int, tags: list[str]) -> None:
        """Update tags of an existing note."""
        return self._call("updateNoteTags", note=note_id, tags=tags)

    def sync(self) -> None:
        """Trigger AnkiWeb sync.

        Fire-and-forget: a successful response means Anki accepted the
        request, not that AnkiWeb has received the data. If a blocking
        dialog appears in Anki (e.g. conflict resolution), the sync
        may remain queued silently.

        Requires AnkiWeb credentials configured in Anki.
        """
        return self._call("sync")

    def ensure_deck_and_model(self, deck_name: str, model_name: str) -> bool:
        """Verify that the deck exists and the model is available.

        Creates the deck if missing. Ensures CocaLevel field exists
        on the model for card migration support. Returns True if
        model is available.
        """
        # Create deck (idempotent)
        self.create_deck(deck_name)

        # Check model exists
        models = self.list_models()
        if model_name not in models:
            raise AnkiConnectError(
                f'Model "{model_name}" not found in Anki. '
                "Please import the .apkg file first to install the model, "
                "then retry syncing."
            )

        # Ensure CocaLevel field exists (for card migration)
        model_fields = self._call("modelFieldNames", modelName=model_name)
        if "CocaLevel" not in model_fields:
            self._call("modelFieldAdd",
                       modelName=model_name, fieldName="CocaLevel")

        return True

    def query_anki_all_lemmas(self) -> set[str]:
        """Return ALL lemmas from ALL notes of model 'Vocabulary Card (WeRead)'.

        Strips bookId suffix from WordId.
        Used for cross-deck dedup in full-text mode.

        Returns empty set if no notes exist or on AnkiConnect error.
        """
        try:
            note_ids = self.find_notes('note:"Vocabulary Card (WeRead)"')
            if not note_ids:
                return set()
            info = self.notes_info(note_ids)
            lemmas: set[str] = set()
            for note in info:
                word_id = note.get("fields", {}).get("WordId", {}).get("value", "")
                if word_id and "_" in word_id:
                    # WordId: {lemma}_{pos}_{bookId}
                    lemma_pos = word_id.rsplit("_", 1)[0]
                    lemmas.add(lemma_pos.lower())
                    # Also add bare lemma for callers that lack POS context
                    parts = lemma_pos.split("_", 1)
                    if len(parts) == 2:
                        lemmas.add(parts[0].lower())
            return lemmas
        except AnkiConnectError:
            return set()
        except Exception:
            return set()

    def find_deck_for_book_id(self, book_id: str) -> tuple[str | None, int]:
        """Find the existing deck name for cards belonging to a given book_id.

        Searches all notes whose WordId ends with ``_{book_id}``, then
        uses ``cardsInfo`` to look up the deck name of the first match.
        Returns ``(deck_name, note_count)``.  If no existing cards are
        found, returns ``(None, 0)``.

        Used by ``sync_anki`` to prevent deck-name drift across batches
        (e.g. accent variations in author names).
        """
        try:
            notes = self.find_notes(f"WordId:*_{book_id}")
            if not notes:
                return None, 0
            count = len(notes)
            card_ids = self.get_cards_of_notes(notes[:1])
            if not card_ids:
                return None, count
            info = self._call("cardsInfo", cards=[card_ids[0]])
            deck_name: str | None = info[0]["deckName"] if info else None
            return deck_name, count
        except AnkiConnectError:
            return None, 0
        except Exception:
            return None, 0

    # ------------------------------------------------------------------
    # Deck mutation
    # ------------------------------------------------------------------

    def change_deck(self, card_ids: list[int], deck: str) -> bool:
        """Move cards to a different deck (preserves review history).

        Used for:
          - Migrating cards to correct COCA-level sub-deck
          - Renaming sub-decks (create new deck, move cards, leave old empty)
        """
        return self._call("changeDeck", cards=card_ids, deck=deck)

    # ------------------------------------------------------------------
    # Vocab-book helpers
    # ------------------------------------------------------------------

    def get_word_id_map_with_deck(
        self, parent_deck: str
    ) -> dict[str, tuple[int, str]]:
        """Return {WordId: (note_id, current_deck)} for ALL notes under a parent.

        Uses recursive deck search ``deck:"parent"`` which inherently
        includes all sub-decks.  Returns both the note_id and the
        *current* deck name for each card, enabling:

          - Parent-level dedup (single lookup covers all sub-decks)
          - Card migration detection (compare current_deck vs target_deck)

        Batches notesInfo calls (50 notes per batch) to avoid exceeding
        AnkiConnect's response buffer (~11MB for 300+ cards).
        """
        note_ids = self.find_notes(
            f'deck:"{parent_deck}" note:"Vocabulary Card (WeRead)"'
        )
        if not note_ids:
            return {}

        # Batch notesInfo to avoid oversized responses
        BATCH = 50
        info: list[dict] = []
        for i in range(0, len(note_ids), BATCH):
            info.extend(self.notes_info(note_ids[i:i + BATCH]))

        # Collect all card IDs then look up deck names in one batch
        note_to_cards: dict[int, list[int]] = {}
        all_card_ids: list[int] = []
        for n in info:
            cards = n.get("cards", [])
            note_to_cards[n["noteId"]] = cards
            all_card_ids.extend(cards)

        if not all_card_ids:
            return {}

        # Batch cardsInfo as well (defense-in-depth)
        note_deck: dict[int, str] = {}
        for i in range(0, len(all_card_ids), BATCH):
            cards_info = self._call("cardsInfo", cards=all_card_ids[i:i + BATCH])
            for card in cards_info:
                nid = card.get("note")
                if nid not in note_deck:
                    note_deck[nid] = card.get("deckName", parent_deck)

        result: dict[str, tuple[int, str]] = {}
        for n in info:
            word_id = (n.get("fields", {})
                        .get("WordId", {})
                        .get("value", ""))
            if not word_id:
                continue
            nid = n["noteId"]
            deck_name = note_deck.get(nid, parent_deck)
            result[word_id] = (nid, deck_name)

        return result

    def find_vocab_book_suffix(
        self, title: str, author: str
    ) -> tuple[str | None, str | None]:
        """Find existing vocab-book deck and extract UUID suffix.

        Searches for a parent deck matching
        ``{title} ({author}) - 分级词汇`` and extracts the 12-char hex
        suffix from any card's WordId field.

        Returns ``(parent_deck_name, suffix)`` or ``(None, None)``.
        """
        target = f"{title} ({author}) - 分级词汇"
        try:
            all_decks = self.deck_names_and_ids()
        except AnkiConnectError:
            return None, None

        # Exact match preferred; also match any deck starting with this prefix
        matched = None
        for deck in all_decks:
            if deck == target or deck.startswith(target):
                matched = deck
                break
        if not matched:
            return None, None

        try:
            note_ids = self.find_notes(
                f'deck:"{matched}" note:"Vocabulary Card (WeRead)"'
            )
            if not note_ids:
                return None, None
            info = self.notes_info(note_ids[:5])
            for note in info:
                word_id = (note.get("fields", {})
                            .get("WordId", {})
                            .get("value", ""))
                # WordId: {lemma}_{pos}_{12-hex-suffix}
                parts = word_id.rsplit("_", 1)
                if len(parts) == 2:
                    candidate = parts[1]
                    if (len(candidate) == 12
                            and all(c in "0123456789abcdef" for c in candidate)):
                        return matched, candidate
        except AnkiConnectError:
            return None, None

        return None, None
