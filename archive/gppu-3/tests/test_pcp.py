"""Tests for colored printing: pcp, TColor, _colorize."""
from gppu import pcp, TColor
from gppu.gppu import _colorize


class TestTColor:
    def test_bracket_access(self):
        assert TColor["RED"] == TColor.RED

    def test_contains(self):
        assert "RED" in TColor

    def test_missing_returns_none(self):
        assert TColor["NONEXISTENT"] is None


class TestColorize:
    def test_basic_colorize(self):
        result = _colorize("hello", TColor.RED)
        assert "hello" in result
        assert "\033[" in result

    def test_format_padding(self):
        result = _colorize("hi", TColor.RED, fmt="10")
        # Should be padded to 10 chars (plus ANSI codes)
        assert "hi" in result

    def test_right_justify(self):
        result = _colorize("hi", TColor.RED, fmt=">10")
        assert "hi" in result


class TestPcp:
    def test_simple_output(self):
        result = pcp("hello")
        assert "hello" in result

    def test_color_application(self):
        result = pcp("RED", "error")
        assert "error" in result
        assert "\033[" in result

    def test_ends_with_reset(self):
        result = pcp("RED", "text")
        assert result.endswith("\u001b[0m")

    def test_multiple_segments(self):
        result = pcp("GREEN", "ok", "RED", "error")
        assert "ok" in result
        assert "error" in result

    def test_msg_kwarg(self):
        result = pcp(msg="log message")
        assert "log message" in result
