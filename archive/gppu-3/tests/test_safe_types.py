"""Tests for safe type coercion: safe_int, safe_float, safe_list."""
import math
from gppu import safe_int, safe_float, safe_list


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


class TestSafeList:
    def test_string_becomes_single_element_list(self):
        assert safe_list("hello") == ["hello"]

    def test_list_passes_through(self):
        assert safe_list([1, 2, 3]) == [1, 2, 3]

    def test_list_filters_falsy(self):
        assert safe_list([1, None, 0, "", 2]) == [1, 2]

    def test_dict_returns_keys(self):
        assert safe_list({"a": 1, "b": 2}) == ["a", "b"]

    def test_none_returns_empty(self):
        assert safe_list(None) == []

    def test_empty_string_returns_single_element(self):
        # empty string is truthy for isinstance but falsy, so safe_list returns [""]
        assert safe_list("") == [""]
