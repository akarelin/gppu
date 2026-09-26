"""Tests for template_populate and dict_template_populate."""
from gppu import template_populate, dict_template_populate


class TestTemplatePopulate:
    def test_simple_substitution(self):
        result = template_populate("Hello $name", {"name": "World"})
        assert result == "Hello World"

    def test_no_substitution_needed(self):
        result = template_populate("plain text", {})
        assert result == "plain text"

    def test_missing_variable_left_as_is(self):
        result = template_populate("$missing", {})
        assert result == "$missing"

    def test_int_passthrough(self):
        # Non-dict scalars go through str() then __tp; int/bool/float inside
        # dicts are preserved, but top-level scalars become strings
        result = template_populate(42, {})
        assert result == "42"

    def test_bool_passthrough(self):
        result = template_populate(True, {})
        assert result == "True"

    def test_float_passthrough(self):
        result = template_populate(3.14, {})
        assert result == "3.14"

    def test_del_returns_none(self):
        assert template_populate("DEL", {}) is None

    def test_list_template_in_string(self):
        # List-in-string only triggers when '$' is present and result starts with '['
        result = template_populate("[1, 2, 3]", {})
        assert result == "[1, 2, 3]"  # No '$' so no template processing

    def test_list_template_with_variable(self):
        # Decimal strings get coerced to int by template_populate
        result = template_populate("[$a, $b]", {"a": "1", "b": "2"})
        assert result == [1, 2]

    def test_list_elements_substituted(self):
        # Inside a dict, list elements are substituted properly
        result = template_populate({"items": ["$a", "$b"]}, {"a": "x", "b": "y"})
        assert result["items"] == ["x", "y"]


class TestDictTemplatePopulate:
    def test_dict_substitution(self):
        template = {"greeting": "Hello $name", "count": 5}
        result = dict_template_populate(template, {"name": "World"})
        assert result["greeting"] == "Hello World"
        assert result["count"] == 5

    def test_nested_dict_substitution(self):
        template = {"outer": {"inner": "$val"}}
        result = dict_template_populate(template, {"val": "filled"})
        assert result["outer"]["inner"] == "filled"

    def test_del_removes_key_value(self):
        template = {"keep": "yes", "remove": "DEL"}
        result = dict_template_populate(template, {})
        assert result["keep"] == "yes"
        assert result["remove"] is None

    def test_non_dict_returns_empty_dict(self):
        result = dict_template_populate("not a dict", {})
        assert result == {}

    def test_data_key_merged(self):
        template = {"data": {"x": "1"}, "val": "$x"}
        result = dict_template_populate(template, {})
        assert result["val"] == "1"
