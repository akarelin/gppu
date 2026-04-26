"""Tests for OS detection."""
from gppu.gppu import detect_os, OSType


class TestDetectOs:
    def test_returns_os_type(self):
        result = detect_os()
        assert isinstance(result, OSType)

    def test_valid_values(self):
        result = detect_os()
        assert result in [OSType.W11, OSType.LINUX, OSType.WSL, OSType.MACOS, OSType.OTHER]


class TestTopLevelSurface:
    def test_OSType_importable_from_gppu(self):
        from gppu import OSType as TopLevelOSType
        assert TopLevelOSType is OSType

    def test_detect_os_importable_from_gppu(self):
        from gppu import detect_os as top_detect_os
        assert top_detect_os is detect_os

    def test_OSType_in_all(self):
        import gppu
        assert 'OSType' in gppu.__all__
        assert 'detect_os' in gppu.__all__
