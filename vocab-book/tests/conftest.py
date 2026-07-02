"""Fixtures for vocab-book tests."""

import sys
from pathlib import Path

import pytest

# skills/ repo root — needed for "from lib.coca import ..." (package-style import)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # vocab-book/tests/ → vocab-book/ → skills/
sys.path.insert(0, str(_REPO_ROOT))

# Also add vocab-book/ for direct filter_fulltext import in tests
_SKILL_DIR = _REPO_ROOT / "vocab-book"
sys.path.insert(0, str(_SKILL_DIR))


@pytest.fixture(scope="session")
def coca_set():
    """Load COCA word set (cached across tests)."""
    from lib.coca import load_coca

    return load_coca()
