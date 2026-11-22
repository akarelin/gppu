"""Tests for safe type coercion: safe_int, safe_float."""
import math
from gppu import safe_int, safe_float


class TestSafeFloat:
    def test_none_returns_default(self):
        assert math.isnan(safe_float(None))

    def test_none_returns_custom_default(self):
        assert safe_float(None, default=0.0) == 0.0

    def test_int_input(self):
        assert safe_float(42) == 42.0

    def test_float_input(self):
        assert safe_float(3.14) == 3.14

    def test_string_number(self):
        assert safe_float("3.14") == 3.14

    def test_string_with_celsius_suffix(self):
        assert safe_float("22.5°c") == 22.5

    def test_string_with_percent_suffix(self):
        assert safe_float("85%") == 85.0

    def test_invalid_string_returns_default(self):
        assert math.isnan(safe_float("not_a_number"))

    def test_empty_string_returns_default(self):
        assert safe_float("", default=0.0) == 0.0

    def test_boolean_true(self):
        assert safe_float(True) == 1.0

    def test_boolean_false(self):
        assert safe_float(False) == 0.0


class TestSafeInt:
    def test_none_returns_default(self):
        assert safe_int(None) == 0

    def test_int_input(self):
        assert safe_int(42) == 42

    def test_float_input(self):
        assert safe_int(3.7) == 3

    def test_string_number(self):
        assert safe_int("42") == 42

    def test_invalid_string_returns_default(self):
        assert safe_int("abc") == 0

    def test_custom_default(self):
        assert safe_int(None, default=-1) == -1
