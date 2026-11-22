"""Tests for gppu.iot's value types."""


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


# // TestAsyncLoopThread removed: _AsyncLoopThread/_ControlBase left gppu.iot in the async/IoT refactor (4e92486); the replacement lifecycle is covered by tests/test_async.py and tests/test_async_iot.py.
