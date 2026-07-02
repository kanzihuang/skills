"""Shared fixtures for lib/ tests."""

import sys
from pathlib import Path

import pytest

# skills/ repo root — needed for "from lib.coca import ..." (package-style import)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # lib/tests/ → lib/ → skills/
sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(scope="session")
def coca_set():
    """Load COCA word set (cached across tests)."""
    from lib.coca import load_coca

    return load_coca()


@pytest.fixture(scope="session")
def coca_ranked():
    """Load COCA frequency-ranked list."""
    from lib.coca import load_freq_ranked

    return load_freq_ranked()


@pytest.fixture(scope="session")
def cmudict():
    """Load CMU pronunciation dictionary."""
    from lib.sync_anki import _load_cmudict

    return _load_cmudict()
