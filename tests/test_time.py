"""Tests for time utilities: now_ts."""
import re
from pathlib import Path

from gppu import now_ts


class TestNowTs:
    def test_returns_float(self):
        assert isinstance(now_ts(), float)

    def test_recent_timestamp(self):
        assert now_ts() > 1700000000  # .. After Nov 2023
