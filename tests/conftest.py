"""Shared fixtures for gppu tests."""
import sys
from pathlib import Path

# Add repo root to path for direct execution (without pip install -e)
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture(autouse=True)
def one_gppufs_per_test():
    """gppufs is one object in a process; each test starts with its own, as a new process does."""
    from gppu.fs.gppufs import GppuFileSystem, _INDEXES
    GppuFileSystem.clear_instance_cache()
    _INDEXES.clear()
    yield
