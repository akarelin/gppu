"""Tests for dict utilities: deepget, deepget_int, deepget_list, deepget_dict, deepdict."""
from gppu import (
    deepget, deepget_int, deepget_list, deepget_dict,
    deepdict,
)
from gppu import glob


class TestDeepget:
    def test_simple_key(self):
        assert deepget("a", {"a": 1}) == 1

    def test_nested_path(self):
        d = {"a": {"b": {"c": 42}}}
        assert deepget("a/b/c", d) == 42

    def test_missing_key_returns_default(self):
        assert deepget("x/y", {"a": 1}, default="nope") == "nope"

    def test_missing_key_returns_none(self):
        assert deepget("x", {}) is None

    def test_top_level_key_with_slash_in_keys(self):
        # If the exact key "a/b" exists, it should be returned directly
        d = {"a/b": "direct", "a": {"b": "nested"}}
        assert deepget("a/b", d) == "direct"

    def test_two_level_path(self):
        d = {"db": {"host": "localhost", "port": 5432}}
        assert deepget("db/host", d) == "localhost"
        assert deepget("db/port", d) == 5432

    def test_default_when_intermediate_missing(self):
        d = {"a": {"b": 1}}
        assert deepget("a/c/d", d, default="fallback") == "fallback"

    def test_a_falsy_value_at_a_path_is_the_value(self):
        from collections import UserDict
        d = {"rest": {"enabled": False, "count": 0, "name": "", "none": None, "deep": UserDict({"on": False})}}
        assert deepget("rest/enabled", d, default=True) is False
        assert deepget("rest/count", d, default=5) == 0
        assert deepget("rest/name", d, default="x") == ""
        assert deepget("rest/none", d, default="x") is None
        assert deepget("rest/deep/on", d, default=True) is False
        assert deepget("rest/name/below", d, default="x") == "x"   # a step that is no mapping

    def test_environment_reads_a_nested_false(self, ran):
        ran({"rest": {"enabled": False}})
        assert glob("rest/enabled") is False


class TestDeepgetTyped:
    def test_deepget_int_returns_int(self):
        d = {"count": 5}
        assert deepget_int("count", d) == 5

    def test_deepget_int_returns_default_for_non_int(self):
        d = {"count": "five"}
        assert deepget_int("count", d, default=0) == 0

    def test_deepget_list_returns_list(self):
        d = {"items": [1, 2, 3]}
        assert deepget_list("items", d) == [1, 2, 3]

    def test_deepget_list_returns_default_for_non_list(self):
        d = {"items": "single"}
        assert deepget_list("items", d, default=[]) == []

    def test_deepget_dict_returns_dict(self):
        d = {"config": {"key": "val"}}
        assert deepget_dict("config", d) == {"key": "val"}

    def test_deepget_dict_returns_default_for_non_dict(self):
        d = {"config": "string"}
        assert deepget_dict("config", d, default={}) == {}


class TestDeepdict:
    def test_creates_nested_defaultdict(self):
        d = deepdict()
        d["a"]["b"]["c"] = 42
        assert d["a"]["b"]["c"] == 42
