"""Tests for gppu.gppu.format_size."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gppu import format_size
from gppu.gppu import format_size as _data_format_size


# .. ── format_size ──────────────────────────────────────────────────────────

class TestFormatSize:
    def test_bytes(self):
        assert format_size(0) == "0 B"
        assert format_size(1) == "1 B"
        assert format_size(1023) == "1023 B"

    def test_kb(self):
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"
        assert format_size(1024 * 1023) == "1023.0 KB"

    def test_mb(self):
        assert format_size(1024 ** 2) == "1.0 MB"
        assert format_size(int(1.5 * 1024 ** 2)) == "1.5 MB"

    def test_gb(self):
        assert format_size(1024 ** 3) == "1.0 GB"
        assert format_size(int(2.3 * 1024 ** 3)) == "2.3 GB"

    def test_tb(self):
        assert format_size(1024 ** 4) == "1.00 TB"
        assert format_size(int(7.8 * 1024 ** 4)) == "7.80 TB"


# .. ── top-level surface ────────────────────────────────────────────────────

class TestTopLevelSurface:
    def test_importable_from_gppu(self):
        assert format_size is _data_format_size

    def test_in_all(self):
        import gppu
        assert 'format_size' in gppu.__all__
