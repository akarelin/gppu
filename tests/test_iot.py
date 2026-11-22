"""The path types are field types of every _DC, and gppu exports them."""


class TestDCRegistration:
    def test_path_types_registered(self):
        from gppu.gppu import _DC, y2path, y2topic, y2uri
        assert _DC._DC_TYPE_MAP['y2path'] is y2path
        assert _DC._DC_TYPE_MAP['y2topic'] is y2topic
        assert _DC._DC_TYPE_MAP['y2uri'] is y2uri


class TestTopLevelExports:
    def test_reexports(self):
        import gppu
        for name in ('y2list', 'y2path', 'y2topic', 'mixin_Mqtt'):
            assert hasattr(gppu, name), name
