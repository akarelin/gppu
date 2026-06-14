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
                     'mixin_Mqtt', 'Transformer'):
            assert hasattr(gppu, name), name


class TestIORuntime:
    def test_io_run_returns_result(self):
        from gppu.iot import _IORuntime

        class Host(_IORuntime):
            name = 'test-host'

        async def coro():
            return 41 + 1

        host = Host()
        assert host.io_run('key', coro()) == 42
        host._io_loop.call_soon_threadsafe(host._io_loop.stop)

    def test_io_host_walks_parent_chain(self):
        from gppu.iot import _IORuntime, _io_host

        class Host(_IORuntime):
            pass

        class Child:
            def __init__(self, parent): self.parent = parent

        host = Host()
        assert _io_host(Child(Child(host))) is host

    def test_io_host_raises_without_ancestor(self):
        import pytest
        from gppu.iot import _io_host

        class Orphan:
            parent = None

        with pytest.raises(RuntimeError):
            _io_host(Orphan())
