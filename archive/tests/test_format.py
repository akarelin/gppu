# .. archived 2026-11-22: what gppu's reduction removed from tests/test_format.py, as it was last


# .. from fec31bb
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


# .. from fec31bb
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
        # .. 1h ago in ISO format with Z suffix
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
