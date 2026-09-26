"""Tests for string utilities: pfy, slugify."""
from gppu import pfy, slugify


class TestPfy:
    def test_dict_formatting(self):
        result = pfy({"key": "value"})
        assert "key" in result
        assert result.startswith("\n")

    def test_list_formatting(self):
        result = pfy([1, 2, 3])
        assert "1" in result

    def test_nested_formatting(self):
        result = pfy({"a": {"b": [1, 2]}})
        assert "a" in result


class TestSlugify:
    def test_simple_string(self):
        assert slugify("Hello World") == "hello_world"

    def test_special_characters(self):
        assert slugify("test@email.com") == "test_email_com"

    def test_preserves_underscores(self):
        assert slugify("already_slugged") == "already_slugged"

    def test_numbers_preserved(self):
        assert slugify("room123") == "room123"

    def test_non_string_input(self):
        assert slugify(42) == "42"
