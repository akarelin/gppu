# .. archived 2026-11-22: what gppu's reduction removed from tests/test_safe_types.py, as it was last


# .. from fec31bb
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
        # .. empty string is truthy for isinstance but falsy, so safe_list returns [""]
        assert safe_list("") == [""]
