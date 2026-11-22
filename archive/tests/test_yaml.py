# .. archived 2026-11-22: what gppu's reduction removed from tests/test_yaml.py, as it was last


# .. from fec31bb
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
        result = dict_sanitize(data, sort_keys=True)
        keys = list(result.keys())
        assert keys[0] == "name"  # .. KEYS_FIRST priority
