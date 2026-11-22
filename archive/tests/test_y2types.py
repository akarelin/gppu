# .. archived 2026-11-22: what gppu's reduction removed from tests/test_y2types.py, as it was last


# .. from fec31bb
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


# .. from fec31bb
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
