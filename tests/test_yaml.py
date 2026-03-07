"""Tests for YAML operations: dict_from_yml, dict_to_yml, dict_sanitize."""
import tempfile
from pathlib import Path

from gppu import dict_from_yml, dict_to_yml, dict_sanitize


class TestDictFromYml:
    def test_load_simple_yaml(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("key: value\nnumber: 42\n")
        result = dict_from_yml(str(f))
        assert result["key"] == "value"
        assert result["number"] == 42

    def test_load_nested_yaml(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("db:\n  host: localhost\n  port: 5432\n")
        result = dict_from_yml(str(f))
        assert result["db"]["host"] == "localhost"
        assert result["db"]["port"] == 5432

    def test_include_directive(self, tmp_path):
        included = tmp_path / "included.yaml"
        included.write_text("host: db.example.com\nport: 5432\n")
        main = tmp_path / "main.yaml"
        main.write_text(f"app: myapp\ndb: !include {included}\n")
        result = dict_from_yml(str(main))
        assert result["app"] == "myapp"
        assert result["db"]["host"] == "db.example.com"

    def test_relative_include(self, tmp_path):
        included = tmp_path / "sub.yaml"
        included.write_text("val: 123\n")
        main = tmp_path / "main.yaml"
        main.write_text("data: !include sub.yaml\n")
        result = dict_from_yml(str(main))
        assert result["data"]["val"] == 123

    def test_accepts_path_object(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("x: 1\n")
        result = dict_from_yml(f)
        assert result["x"] == 1


class TestDictToYml:
    def test_write_and_read_roundtrip(self, tmp_path):
        f = str(tmp_path / "out.yaml")
        data = {"name": "test", "count": 42, "items": ["a", "b"]}
        dict_to_yml(f, data)
        result = dict_from_yml(f)
        assert result["name"] == "test"
        assert result["count"] == 42

    def test_none_data_skips_write(self, tmp_path):
        f = tmp_path / "out.yaml"
        dict_to_yml(str(f), None)
        assert not f.exists()

    def test_nested_dict_roundtrip(self, tmp_path):
        f = str(tmp_path / "nested.yaml")
        data = {"level1": {"level2": {"level3": "deep"}}}
        dict_to_yml(f, data)
        result = dict_from_yml(f)
        assert result["level1"]["level2"]["level3"] == "deep"


class TestDictSanitize:
    def test_simple_dict(self):
        result = dict_sanitize({"name": "test", "count": 42})
        assert result["name"] == "test"
        assert result["count"] == 42

    def test_nested_dict(self):
        data = {"outer": {"inner": "value"}}
        result = dict_sanitize(data)
        assert result["outer"]["inner"] == "value"

    def test_list_input(self):
        result = dict_sanitize([1, 2, 3])
        assert isinstance(result, list)
        assert 1 in result

    def test_none_values_preserved(self):
        result = dict_sanitize({"key": None})
        assert result["key"] is None

    def test_keys_sorted_with_priority(self):
        data = {"z": 1, "name": "first", "a": 2}
        result = dict_sanitize(data)
        keys = list(result.keys())
        assert keys[0] == "name"  # KEYS_FIRST priority
