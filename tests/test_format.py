"""Tests for gppu.data.format_size / format_duration / format_since."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gppu import format_size, format_duration, format_since
from gppu.data import (
    format_size as _data_format_size,
    format_duration as _data_format_duration,
    format_since as _data_format_since,
)


# ── format_size ──────────────────────────────────────────────────────────

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


# ── format_duration ──────────────────────────────────────────────────────

class TestFormatDuration:
    def test_negative(self):
        assert format_duration(-5) == "-"

    def test_zero(self):
        assert format_duration(0) == "0s"

    def test_seconds(self):
        assert format_duration(1) == "1s"
        assert format_duration(59) == "59s"

    def test_minutes(self):
        assert format_duration(60) == "1m 0s"
        assert format_duration(125) == "2m 5s"
        assert format_duration(3599) == "59m 59s"

    def test_hours(self):
        assert format_duration(3600) == "1h 0m"
        assert format_duration(3600 * 2 + 60 * 5) == "2h 5m"


# ── format_since ─────────────────────────────────────────────────────────

class TestFormatSince:
    def test_seconds(self):
        dt = datetime.now(timezone.utc) - timedelta(seconds=30)
        assert format_since(dt) == "30s"

    def test_minutes(self):
        dt = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert format_since(dt) == "5m"

    def test_hours(self):
        dt = datetime.now(timezone.utc) - timedelta(hours=2)
        assert format_since(dt) == "2h"

    def test_days(self):
        dt = datetime.now(timezone.utc) - timedelta(days=3)
        assert format_since(dt) == "3d"

    def test_weeks(self):
        dt = datetime.now(timezone.utc) - timedelta(days=14)
        assert format_since(dt) == "2w"

    def test_months(self):
        dt = datetime.now(timezone.utc) - timedelta(days=90)
        assert format_since(dt) == "3mo"

    def test_years(self):
        dt = datetime.now(timezone.utc) - timedelta(days=800)
        assert format_since(dt) == "2y"

    def test_iso_string_with_z(self):
        # 1h ago in ISO format with Z suffix
        dt = datetime.now(timezone.utc) - timedelta(hours=1)
        iso = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        assert format_since(iso) == "1h"

    def test_iso_string_with_offset(self):
        dt = datetime.now(timezone.utc) - timedelta(minutes=10)
        iso = dt.isoformat()
        assert format_since(iso) == "10m"

    def test_epoch(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=3)).timestamp()
        assert format_since(ts) == "3h"

    def test_invalid_string(self):
        assert format_since("not a date") == ""
        assert format_since("") == ""

    def test_invalid_type(self):
        assert format_since(None) == ""
        assert format_since([]) == ""

    def test_future_returns_zero(self):
        dt = datetime.now(timezone.utc) + timedelta(hours=1)
        assert format_since(dt) == "0s"


# ── top-level surface ────────────────────────────────────────────────────

class TestTopLevelSurface:
    def test_importable_from_gppu(self):
        assert format_size is _data_format_size
        assert format_duration is _data_format_duration
        assert format_since is _data_format_since

    def test_in_all(self):
        import gppu
        assert 'format_size' in gppu.__all__
        assert 'format_duration' in gppu.__all__
        assert 'format_since' in gppu.__all__
