"""Fixtures for vocab-anki tests."""
import sys
from pathlib import Path

import pytest

# Add vocab-anki/ (for filter_pipeline) and skills/ (for lib.*) to sys.path
_SKILL_DIR = Path(__file__).resolve().parent.parent  # vocab-anki/
_REPO_ROOT = _SKILL_DIR.parent                         # skills/
sys.path.insert(0, str(_SKILL_DIR))
sys.path.insert(0, str(_REPO_ROOT))
