"""Tests for time utilities: now_str, now_ts, pretty_timedelta,
prepend_datestamp, append_timestamp, DelayedOff."""
import re
import time
from pathlib import Path

from gppu import DelayedOff, now_str, now_ts, pretty_timedelta, prepend_datestamp, append_timestamp


class TestNowStr:
    def test_format(self):
        result = now_str()
        assert re.match(r"\d{8}\.\d{6}", result)


class TestNowTs:
    def test_returns_float(self):
        assert isinstance(now_ts(), float)

    def test_recent_timestamp(self):
        assert now_ts() > 1700000000  # After Nov 2023


class TestPrettyTimedelta:
    def test_seconds_only(self):
        ts = now_ts() - 30
        result = pretty_timedelta(ts)
        assert "s" in result
        assert "m" not in result

    def test_minutes(self):
        ts = now_ts() - 120
        result = pretty_timedelta(ts)
        assert "m" in result

    def test_hours(self):
        ts = now_ts() - 7200
        result = pretty_timedelta(ts)
        assert "h" in result

    def test_days(self):
        ts = now_ts() - 172800
        result = pretty_timedelta(ts)
        assert "d" in result


class TestPrependDatestamp:
    def test_prepends_datestamp(self):
        result = prepend_datestamp("/tmp/file.txt")
        name = result.name
        assert re.match(r"\d{6} file\.txt", name)

    def test_custom_separator(self):
        result = prepend_datestamp("/tmp/file.txt", separator="_")
        name = result.name
        assert re.match(r"\d{6}_file\.txt", name)

    def test_preserves_directory(self):
        result = prepend_datestamp("/some/dir/file.txt")
        assert result.parent.parts[-2:] == ("some", "dir")


class TestAppendTimestamp:
    def test_appends_timestamp(self):
        result = append_timestamp("/tmp/backup.tar.gz")
        name = result.name
        assert "backup" in name
        assert re.search(r"\d{6}-\d{4}", name)

    def test_preserves_extension(self):
        result = append_timestamp("/tmp/data.csv")
        assert result.suffix == ".csv"

    def test_preserves_directory(self):
        result = append_timestamp("/some/dir/file.txt")
        assert result.parent.parts[-2:] == ("some", "dir")


class TestDelayedOff:
    def test_off_until_first_edge(self):
        assert DelayedOff(1).held is False

    def test_edge_holds_then_drops(self):
        d = DelayedOff(0.05)
        assert d.retrigger() is True
        assert d.held is True
        time.sleep(0.08)
        assert d.held is False

    def test_edge_restarts_the_countdown(self):
        d = DelayedOff(0.12)
        d.retrigger()
        time.sleep(0.08)
        d.retrigger()
        time.sleep(0.08)
        assert d.held is True   # 0.16s since the first edge, 0.08s since the last

    def test_replayed_stamp_is_not_an_edge(self):
        d = DelayedOff(1)
        assert d.retrigger(stamp=1000.0) is True
        assert d.retrigger(stamp=1000.0) is False   # same edge redelivered
        assert d.retrigger(stamp=999.0) is False    # older edge
        assert d.retrigger(stamp=1001.0) is True

    def test_replay_does_not_extend_the_hold(self):
        d = DelayedOff(0.12)
        d.retrigger(stamp=1000.0)
        time.sleep(0.08)
        d.retrigger(stamp=1000.0)   # replay: must not restart the countdown
        time.sleep(0.08)
        assert d.held is False

    def test_nan_stamp_is_rejected(self):
        d = DelayedOff(1)
        assert d.retrigger(stamp=float("nan")) is False
        assert d.held is False

    def test_sender_clock_offset_does_not_move_the_hold(self):
        """The rule: a remote stamp is comparable only to another stamp from the
        same sender. A sender hours out of step with us must not shorten, extend
        or skip the hold."""
        for stamp in (now_ts() - 86400, now_ts() + 86400, 1.0):
            d = DelayedOff(0.05)
            assert d.retrigger(stamp=stamp) is True
            assert d.held is True
            assert d.remaining <= 0.05
            time.sleep(0.08)
            assert d.held is False

    def test_remaining_is_zero_when_off(self):
        d = DelayedOff(1)
        assert d.remaining == 0.0
        d.retrigger()
        assert 0 < d.remaining <= 1
        d.clear()
        assert d.remaining == 0.0
        assert d.held is False
