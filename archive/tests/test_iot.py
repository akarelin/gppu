# .. archived 2026-11-22: what gppu's reduction removed from tests/test_iot.py, as it was last


# .. from fec31bb
class TestTopicMatches:
    def test_exact(self):
        assert mixin_Mqtt._topic_matches('a/b/c', 'a/b/c')
        assert not mixin_Mqtt._topic_matches('a/b/c', 'a/b')

    def test_hash_wildcard_prefix(self):
        assert mixin_Mqtt._topic_matches('a/b/c', 'a/#')
        assert mixin_Mqtt._topic_matches('a/b', 'a/b/#')  # .. prefix match
        assert not mixin_Mqtt._topic_matches('x/b/c', 'a/#')


class TestDCRegistration:
  # .. from fec31bb
    def test_y2_types_registered(self):
        from gppu.gppu import _DC, _DC_BASE_TYPE_MAP
        from gppu.iot import y2eid, y2topic
        assert _DC_BASE_TYPE_MAP['y2eid'] is y2eid
        assert _DC_BASE_TYPE_MAP['y2topic'] is y2topic
        assert _DC._DC_TYPE_MAP['y2eid'] is y2eid
        assert _DC._DC_TYPE_MAP['y2topic'] is y2topic
