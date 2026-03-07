"""Tests for DC (pseudo-DataClass)."""
from gppu import DC


class TestDC:
    def test_basic_subclass(self):
        class Item(DC):
            name: str
            count: int

        item = Item(name="widget", count=5)
        assert item.name == "widget"
        assert item.count == 5

    def test_default_values(self):
        class Item(DC):
            name: str
            items: list
            config: dict

        item = Item()
        assert item.name == ""
        assert item.items == []
        assert item.config == {}

    def test_property_setter(self):
        class Item(DC):
            name: str

        item = Item()
        item.name = "updated"
        assert item.name == "updated"

    def test_data_dict_access(self):
        class Item(DC):
            name: str

        item = Item(name="test")
        assert item.data["name"] == "test"

    def test_userdict_behavior(self):
        class Item(DC):
            name: str

        item = Item(name="test")
        assert item["name"] == "test"

    def test_inheritance(self):
        class Base(DC):
            name: str

        class Child(Base):
            extra: int

        child = Child(name="base", extra=42)
        assert child.name == "base"
        assert child.extra == 42

    def test_data_kwarg_as_string(self):
        class Item(DC):
            name: str

        # When data kwarg is a string, it gets wrapped: {"data": "raw"}
        item = Item(data="raw")
        assert item.data == {"data": "raw"}
