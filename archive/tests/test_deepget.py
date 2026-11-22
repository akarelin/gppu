# .. archived 2026-11-22: what gppu's reduction removed from tests/test_deepget.py, as it was last


# .. from fec31bb
class TestDeepdict:
    def test_creates_nested_defaultdict(self):
        d = deepdict()
        d["a"]["b"]["c"] = 42
        assert d["a"]["b"]["c"] == 42
