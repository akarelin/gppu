"""Tests for dict utilities: deepget, deepget_int, deepget_list, deepget_dict,
dict_all_paths, dict_element_append, dict_sort_keylen, deepdict."""
from gppu import (
    deepget, deepget_int, deepget_list, deepget_dict,
    dict_all_paths, dict_element_append, dict_sort_keylen, deepdict,
)


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


class TestDictAllPaths:
    def test_flat_dict(self):
        d = {"a": 1, "b": 2}
        paths = dict_all_paths(d)
        assert "a" in paths
        assert "b" in paths

    def test_nested_dict(self):
        d = {"a": {"b": {"c": 1}}}
        paths = dict_all_paths(d)
        assert "a" in paths
        assert "a/b" in paths
        assert "a/b/c" in paths

    def test_mixed_dict(self):
        d = {"x": 1, "y": {"z": 2}}
        paths = dict_all_paths(d)
        assert set(paths) == {"x", "y", "y/z"}


class TestDictElementAppend:
    def test_append_to_new_key(self):
        d = {}
        dict_element_append(d, "k", "v")
        assert d["k"] == ["v"]

    def test_append_to_existing_list(self):
        d = {"k": [1]}
        dict_element_append(d, "k", 2)
        assert d["k"] == [1, 2]

    def test_append_to_existing_string(self):
        d = {"k": "old"}
        dict_element_append(d, "k", "new")
        assert d["k"] == ["old", "new"]

    def test_unique_prevents_duplicates(self):
        d = {"k": [1, 2]}
        dict_element_append(d, "k", 2, unique=True)
        assert d["k"] == [1, 2]

    def test_append_list_value(self):
        d = {}
        dict_element_append(d, "k", [1, 2, 3])
        assert d["k"] == [1, 2, 3]


class TestDictSortKeylen:
    def test_sorts_by_key_length_descending(self):
        d = {"a": 1, "bb": 2, "ccc": 3}
        result = dict_sort_keylen(d)
        keys = list(result.keys())
        assert keys == ["ccc", "bb", "a"]

    def test_sorts_ascending(self):
        d = {"a": 1, "bb": 2, "ccc": 3}
        result = dict_sort_keylen(d, reverse=False)
        keys = list(result.keys())
        assert keys == ["a", "bb", "ccc"]

    def test_non_dict_returns_empty(self):
        assert dict_sort_keylen("not a dict") == {}


class TestDeepdict:
    def test_creates_nested_defaultdict(self):
        d = deepdict()
        d["a"]["b"]["c"] = 42
        assert d["a"]["b"]["c"] == 42
