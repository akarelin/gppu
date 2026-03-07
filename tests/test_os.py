"""Tests for OS detection."""
from gppu.gppu import detect_os, OSType


class TestDetectOs:
    def test_returns_os_type(self):
        result = detect_os()
        assert isinstance(result, OSType)

    def test_valid_values(self):
        result = detect_os()
        assert result in [OSType.W11, OSType.LINUX, OSType.WSL, OSType.MACOS, OSType.OTHER]
