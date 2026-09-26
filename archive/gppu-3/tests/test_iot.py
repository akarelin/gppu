"""Tests for gppu.iot mqtt plumbing (offline — no broker)."""
from gppu.iot import mixin_Mqtt


class TestTopicMatches:
    def test_exact(self):
        assert mixin_Mqtt._topic_matches('a/b/c', 'a/b/c')
        assert not mixin_Mqtt._topic_matches('a/b/c', 'a/b')

    def test_hash_wildcard_prefix(self):
        assert mixin_Mqtt._topic_matches('a/b/c', 'a/#')
        assert mixin_Mqtt._topic_matches('a/b', 'a/b/#')  # prefix match
        assert not mixin_Mqtt._topic_matches('x/b/c', 'a/#')


class TestDCRegistration:
    def test_y2_types_registered(self):
        from gppu.gppu import _DC, _DC_BASE_TYPE_MAP
        from gppu.iot import y2eid, y2topic
        assert _DC_BASE_TYPE_MAP['y2eid'] is y2eid
        assert _DC_BASE_TYPE_MAP['y2topic'] is y2topic
        assert _DC._DC_TYPE_MAP['y2eid'] is y2eid
        assert _DC._DC_TYPE_MAP['y2topic'] is y2topic


class TestTopLevelExports:
    def test_reexports(self):
        import gppu
        for name in ('y2list', 'y2path', 'y2topic', 'y2slug', 'y2eid',
                     'mixin_Mqtt'):
            assert hasattr(gppu, name), name


# TestAsyncLoopThread removed: _AsyncLoopThread/_ControlBase left gppu.iot in the
# async/IoT refactor (4e92486); the replacement lifecycle is covered by
# tests/test_async.py and tests/test_async_iot.py.
