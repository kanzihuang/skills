"""AnkiConnect API client for interacting with a running Anki instance.

AnkiConnect is a local HTTP API plugin for Anki desktop. It exposes an
endpoint at http://localhost:8765 and allows programmatic access to create
decks, add notes, store media files, and query existing cards — all while
preserving review history for cards that already exist.

Usage:
    from ankiconnect import AnkiConnect

    ac = AnkiConnect()
    decks = ac.list_decks()
    notes = ac.find_notes_in_deck("The Little Prince Vocabulary")
"""

import base64
import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AnkiConnect client
# ---------------------------------------------------------------------------

ANKICONNECT_URL = "http://localhost:8765"
ANKICONNECT_VERSION = 6
REQUEST_TIMEOUT = 10


class AnkiConnectError(Exception):
    """Raised when AnkiConnect returns an error or is unreachable."""


class AnkiConnect:
    """Thin wrapper around the AnkiConnect JSON-RPC API."""

    def __init__(self, url: str = ANKICONNECT_URL) -> None:
        self.url = url

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    def _call(self, action: str, **params: Any) -> Any:
        """Make a single AnkiConnect call. Raises AnkiConnectError on failure."""
        payload = {
            "action": action,
            "version": ANKICONNECT_VERSION,
            "params": params,
        }
        try:
            resp = requests.post(self.url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.ConnectionError:
            raise AnkiConnectError(
                "Cannot reach AnkiConnect. Is Anki running with the "
                "AnkiConnect plugin installed? (http://localhost:8765)"
            )
        except requests.RequestException as e:
            raise AnkiConnectError(f"AnkiConnect request failed: {e}")

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
            "deck:The Little Prince Vocabulary"
            "deck:English Word:pondered"
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
        """
        return self._call("addNotes", notes=notes)

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
            return self.find_notes(f'deck:"{deck_name}" "{field_name}:{value}"')
        return self.find_notes(f'"{field_name}:{value}"')

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

        Creates the deck if missing. Returns True if model is available.
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
        return True

    def query_anki_all_lemmas(self) -> set[str]:
        """Return ALL lemmas from ALL notes of model 'Vocabulary Card (WeRead)'.

        Strips bookId suffix from WordId, excludes __META__ entries.
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
                if word_id and "_" in word_id and not word_id.startswith("__META__"):
                    lemma = word_id.rsplit("_", 1)[0]
                    lemmas.add(lemma.lower())
            return lemmas
        except AnkiConnectError:
            return set()
        except Exception:
            return set()
