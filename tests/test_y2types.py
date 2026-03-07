"""Tests for y2list, y2path, y2topic, y2slug, y2eid."""
import pytest
from gppu.ad import y2list, y2path, y2topic, y2slug, y2eid


class TestY2List:
    def test_from_string(self):
        yl = y2list("hello")
        assert yl.data == ["hello"]

    def test_from_list(self):
        yl = y2list(["a", "b", "c"])
        assert yl.data == ["a", "b", "c"]

    def test_str_representation(self):
        yl = y2list(["a", "b"])
        assert str(yl) == "ab"  # empty token

    def test_head_and_tail(self):
        yl = y2list(["first", "middle", "last"])
        assert yl.head == "first"
        assert yl.tail == "last"

    def test_empty_head_tail(self):
        yl = y2list(None)
        assert yl.head is None
        assert yl.tail is None

    def test_extract(self):
        yl = y2list(["a", "b", "c"])
        assert yl.extract("b") == "b"
        assert yl.data == ["a", "c"]

    def test_extract_missing(self):
        yl = y2list(["a"])
        assert yl.extract("z", "default") == "default"

    def test_discard(self):
        yl = y2list(["a", "b", "c"])
        yl.discard("b")
        assert yl.data == ["a", "c"]

    def test_pophead(self):
        yl = y2list(["a", "b"])
        assert yl.pophead() == "a"
        assert yl.data == ["b"]

    def test_poptail(self):
        yl = y2list(["a", "b"])
        assert yl.poptail() == "b"
        assert yl.data == ["a"]

    def test_equality(self):
        assert y2list(["a", "b"]) == y2list(["a", "b"])

    def test_hash(self):
        s = {y2list(["a"]), y2list(["a"])}
        assert len(s) == 1


class TestY2Path:
    def test_from_string(self):
        yp = y2path("a/b/c")
        assert yp.data == ["a", "b", "c"]
        assert str(yp) == "a/b/c"

    def test_from_list(self):
        yp = y2path(["a", "b"])
        assert str(yp) == "a/b"

    def test_from_multiple_args(self):
        yp = y2path("a/b", "c/d")
        assert str(yp) == "a/b/c/d"

    def test_endswith(self):
        yp = y2path("sensors/temperature/room")
        assert yp.endswith("room")

    def test_endswith_with_slash(self):
        yp = y2path("sensors/temperature/room")
        assert yp.endswith("temperature/room")

    def test_startswith(self):
        yp = y2path("sensors/temperature")
        assert yp.startswith("sensors")


class TestY2Topic:
    def test_basic(self):
        yt = y2topic("mqtt/sensors/temp")
        assert str(yt) == "mqtt/sensors/temp"

    def test_is_wildcard_hash(self):
        yt = y2topic("mqtt/#")
        assert yt.is_wildcard()

    def test_is_wildcard_plus(self):
        yt = y2topic("mqtt/+/temp")
        assert yt.is_wildcard()

    def test_not_wildcard(self):
        yt = y2topic("mqtt/sensors/temp")
        assert not yt.is_wildcard()


class TestY2Slug:
    def test_basic(self):
        ys = y2slug("hello_world")
        assert str(ys) == "hello_world"

    def test_strips_at_suffix(self):
        ys = y2slug("entity@namespace")
        assert str(ys) == "entity"

    def test_tokenizes_with_underscore(self):
        ys = y2slug("living_room")
        assert ys.data == ["living", "room"]


class TestY2Eid:
    def test_basic_entity_id(self):
        eid = y2eid("light.living_room@yala")
        assert eid.domain == "light"
        assert str(eid.slug) == "living_room"
        assert eid.ns == "yala"

    def test_without_namespace_uses_default(self):
        eid = y2eid("sensor.temperature")
        assert eid.ns == "yala"

    def test_without_domain_uses_default(self):
        eid = y2eid("my_entity@ns1")
        assert eid.domain == "entity"
        assert eid.ns == "ns1"

    def test_startswith(self):
        eid = y2eid("light.living_room@yala")
        assert eid.startswith("living")

    def test_entity_id_property(self):
        eid = y2eid("switch.kitchen@home")
        assert eid.entity_id == "switch.kitchen"

    def test_seid_property(self):
        eid = y2eid("light.bedroom@yala")
        assert eid.seid == "light.bedroom@yala"

    def test_equality(self):
        assert y2eid("light.a@ns") == y2eid("light.a@ns")

    def test_hash_in_set(self):
        s = {y2eid("light.a@ns"), y2eid("light.a@ns")}
        assert len(s) == 1

    def test_ordering(self):
        a = y2eid("light.a@ns")
        b = y2eid("light.b@ns")
        assert a < b

    def test_bool_true(self):
        assert bool(y2eid("light.x@ns"))

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            y2eid("")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            y2eid(None)

    def test_from_dict(self):
        eid = y2eid({"entity_id": "sensor.temp@home"})
        assert eid.domain == "sensor"

    def test_str_roundtrip(self):
        original = "binary_sensor.motion_detected@yala"
        eid = y2eid(original)
        assert str(eid) == original
