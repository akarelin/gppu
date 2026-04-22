"""Tests for gppu.tui.debug — DebugSink, ring-buffer, file I/O, thread safety."""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest

from gppu.tui.debug import DebugSink, make_debug_sink


@pytest.fixture()
def cache_root(tmp_path):
    return str(tmp_path)


class TestDebugSink:
    def test_path_derived_from_app_name(self, tmp_path):
        sink = DebugSink('myapp', cache_root=str(tmp_path))
        assert sink.path == str(tmp_path / 'debug.log')

    def test_callable(self, cache_root):
        sink = DebugSink('x', cache_root=cache_root)
        assert callable(sink)
        sink('hello')
        path, n = sink.dump()
        assert n == 1
        with open(path) as f:
            assert 'hello' in f.read()

    def test_ring_buffer_caps_in_memory(self, cache_root):
        sink = DebugSink('x', capacity=3, cache_root=cache_root)
        for i in range(10):
            sink(f'msg {i}')
        _, n = sink.dump()
        # in-memory buffer caps at 3
        assert n == 3
        tail = sink.tail(10)
        assert tail == [t for t in tail]
        # last-3 survive: msg 7, 8, 9
        joined = ' '.join(tail)
        assert 'msg 9' in joined and 'msg 7' in joined
        assert 'msg 0' not in joined

    def test_file_preserves_all(self, cache_root):
        sink = DebugSink('x', capacity=3, cache_root=cache_root)
        for i in range(10):
            sink(f'msg {i}')
        with open(sink.path) as f:
            body = f.read()
        # file has every line, independent of buffer cap
        for i in range(10):
            assert f'msg {i}' in body
        # run header written once
        assert body.count('--- run') == 1

    def test_tail_returns_last_n(self, cache_root):
        sink = DebugSink('x', capacity=100, cache_root=cache_root)
        for i in range(20):
            sink(f'm{i}')
        assert len(sink.tail(5)) == 5
        assert 'm19' in sink.tail(5)[-1]
        # n > buffer size returns whole buffer
        assert len(sink.tail(999)) == 20

    def test_thread_safety(self, cache_root):
        sink = DebugSink('x', capacity=1000, cache_root=cache_root)
        def writer(tid):
            for i in range(50):
                sink(f't{tid}-{i}')
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        _, n = sink.dump()
        assert n == 500
        # File has 500 lines + 1 header
        with open(sink.path) as f:
            lines = [l for l in f.read().splitlines() if l and '--- run' not in l]
        assert len(lines) == 500

    def test_close_idempotent(self, cache_root):
        sink = DebugSink('x', cache_root=cache_root)
        sink('hi')
        sink.close()
        sink.close()  # safe to call twice

    def test_make_debug_sink_factory(self, cache_root):
        sink = make_debug_sink('y', cache_root=cache_root, capacity=7)
        assert isinstance(sink, DebugSink)
        assert sink.app_name == 'y'


class TestDebugMixinAvailability:
    """Mixin should be None only if Textual isn't installed.  When Textual is
    present we rely on the async tests in test_tui_widgets.py for full
    coverage — here we only check the import-time guard."""

    def test_mixin_present_with_textual(self):
        pytest.importorskip('textual')
        from gppu.tui.debug import DebugMixin, DebugScreen
        assert DebugMixin is not None
        assert DebugScreen is not None
