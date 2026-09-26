"""Shared fixtures for gppu tests."""
import sys
from pathlib import Path

# Add repo root to path for direct execution (without pip install -e)
sys.path.insert(0, str(Path(__file__).parent.parent))
