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


class TestAsyncLoopThread:
    def test_call_returns_result(self):
        from gppu.iot import _AsyncLoopThread

        class Host(_AsyncLoopThread):
            name = 'test-host'

        async def coro():
            return 41 + 1

        host = Host()
        assert host.call(coro) == 42  # daemon loop thread is reaped at process exit

    def test_from_child_walks_parent_chain(self):
        from gppu.iot import _AsyncLoopThread

        class Host(_AsyncLoopThread):
            pass

        class Child:
            def __init__(self, parent): self.parent = parent

        host = Host()
        assert _AsyncLoopThread.from_child(Child(Child(host))) is host

    def test_from_child_raises_without_ancestor(self):
        import pytest
        from gppu.iot import _AsyncLoopThread

        class Orphan:
            parent = None

        with pytest.raises(RuntimeError):
            _AsyncLoopThread.from_child(Orphan())

    def test_control_call_runs_on_host_loop(self):
        from gppu.iot import _AsyncLoopThread, _ControlBase

        class Host(_AsyncLoopThread):
            pass

        class Dev(_ControlBase):
            def __init__(self, parent): self.parent = parent
            async def _op(self, x): return x * 2
            def run(self, x): return self._control_call(self._op, x)

        host = Host()
        assert Dev(host).run(21) == 42  # daemon loop thread is reaped at process exit
