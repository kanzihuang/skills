"""Shared fixtures for vocab-anki tests."""

import sys
from pathlib import Path

import pytest

# Add project root to path for imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# skills/ is needed for "from lib.coca import ..." (package-style import)
# skills/lib/ is needed for "from coca import ..." (direct import)
_REPO_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "lib"))
sys.path.insert(0, str(_REPO_ROOT / "vocab-anki"))


@pytest.fixture(scope="session")
def coca_set():
    """Load COCA word set (cached across tests)."""
    from coca import load_coca

    return load_coca()


@pytest.fixture(scope="session")
def coca_ranked():
    """Load COCA frequency-ranked list."""
    from coca import load_freq_ranked

    return load_freq_ranked()


@pytest.fixture(scope="session")
def cmudict():
    """Load CMU pronunciation dictionary."""
    from sync_anki import _load_cmudict

    return _load_cmudict()
