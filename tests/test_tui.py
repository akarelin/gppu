"""Tests for gppu.tui launcher, widgets, and run_task.

Requires: pip install gppu[test-tui]
Run:  python -m pytest tests/test_tui.py -v
"""
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

pytest.importorskip('textual', reason='textual not installed — skip TUI tests')
pytest.importorskip('pytest_asyncio', reason='pytest-asyncio not installed — skip TUI tests')

from gppu.tui import (  # noqa: E402
    AppItem,
    LauncherApp,
    ModeItem,
    ProcessRow,
    SpinnerIndicator,
    StatusHeader,
)
from textual.widgets import ListView, RichLog, Static  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _tmpscript(tmp_path: Path, name: str, body: str) -> None:
    (tmp_path / name).write_text(textwrap.dedent(body))


def _make_apps(tmp_path: Path) -> dict[str, dict]:
    _tmpscript(tmp_path, 'hello.py', """\
        import sys, time
        for i in range(3):
            print(f"line {i}")
            time.sleep(0.05)
    """)
    _tmpscript(tmp_path, 'echo.py', """\
        import sys
        print(f"args={sys.argv[1:]}")
    """)
    return {
        'inline_app': {
            'name': 'Inline',
            'icon': 'I',
            'description': 'inline test',
            'script': 'hello.py',
            'modes': {
                'run': {'name': 'Run', 'inline': True},
            },
        },
        'multi_mode': {
            'name': 'Multi',
            'icon': 'M',
            'description': 'multi mode test',
            'script': 'hello.py',
            'modes': {
                'a': {'name': 'Mode A', 'inline': True},
                'b': {'name': 'Mode B', 'inline': True},
            },
        },
        'direct_app': {
            'name': 'Direct',
            'icon': 'D',
            'description': 'direct launch',
            'script': 'echo.py',
        },
        'ask_app': {
            'name': 'Ask',
            'icon': 'A',
            'description': 'ask form',
            'script': 'echo.py',
            'modes': {
                'custom': {
                    'name': 'Custom',
                    'ask_for': [
                        {'name': 'msg', 'default': 'hi'},
                    ],
                },
            },
        },
    }


class _TestApp(LauncherApp):
    TITLE = 'Test'
    MENU_TITLE = 'Test Menu'


# ── Widget unit tests ────────────────────────────────────────────────────────

class TestSpinnerIndicator:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        app = _TestApp({}, Path('.'))
        async with app.run_test():
            spinner = SpinnerIndicator()
            await app.mount(spinner)
            spinner.start()
            assert spinner._active
            assert spinner._timer is not None
            spinner.stop()
            assert not spinner._active
            assert spinner._timer is None

    @pytest.mark.asyncio
    async def test_reset_clears(self):
        app = _TestApp({}, Path('.'))
        async with app.run_test():
            spinner = SpinnerIndicator()
            await app.mount(spinner)
            spinner.start()
            spinner.reset()
            assert not spinner._active
            assert spinner._timer is None


class TestProcessRow:
    @pytest.mark.asyncio
    async def test_compose_children(self):
        app = _TestApp({}, Path('.'))
        async with app.run_test():
            row = ProcessRow(1, 'Test Task')
            bar = app.query_one('#process-bar')
            await bar.mount(row)
            assert row.proc_id == 1
            assert row.app_name == 'Test Task'
            assert row.log_lines == []
            assert row.query_one(SpinnerIndicator) is not None
            assert row.query_one('.proc-status', Static) is not None
            assert row.query_one('.log-toggle', Static) is not None


class TestStatusHeader:
    @pytest.mark.asyncio
    async def test_renders(self):
        app = _TestApp({}, Path('.'))
        async with app.run_test():
            assert app.query_one(StatusHeader) is not None


class TestAppItem:
    def test_stores_key_and_def(self):
        d = {'name': 'Foo', 'icon': 'X', 'description': 'bar'}
        item = AppItem('foo', d)
        assert item.app_key == 'foo'
        assert item.app_def is d


class TestModeItem:
    def test_stores_key_and_def(self):
        d = {'name': 'Run', 'inline': True}
        item = ModeItem('run', d)
        assert item.mode_key == 'run'
        assert item.mode_def is d

    def test_none_mode_def(self):
        item = ModeItem('x', None)
        assert item.mode_def == {}


# ── LauncherApp composition ─────────────────────────────────────────────────

class TestLauncherCompose:
    @pytest.mark.asyncio
    async def test_initial_widgets(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test():
            assert app.query_one(StatusHeader)
            assert app.query_one('#process-bar')
            assert app.query_one('#output-panel', RichLog)
            assert app.query_one('#menu')
            assert app.query_one('#menu-title', Static)
            lv = app.query_one('#app-list', ListView)
            assert len(lv.children) == len(apps)

    @pytest.mark.asyncio
    async def test_initial_phase(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test():
            assert app._phase == 'apps'
            assert app._processes == {}
            assert app._active_log is None


# ── Navigation (direct method calls) ────────────────────────────────────────

class TestNavigation:
    @pytest.mark.asyncio
    async def test_back_from_apps_quits(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            await pilot.press('escape')
            assert app.return_value is None

    @pytest.mark.asyncio
    async def test_show_modes(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            app._selected_app = apps['multi_mode']
            app._show_modes(apps['multi_mode'], apps['multi_mode']['modes'])
            await pilot.pause()
            assert app._phase == 'modes'
            lv = app.query_one('#app-list', ListView)
            mode_items = lv.query(ModeItem)
            assert len(mode_items) == 2

    @pytest.mark.asyncio
    async def test_back_from_modes(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            app._selected_app = apps['multi_mode']
            app._show_modes(apps['multi_mode'], apps['multi_mode']['modes'])
            await pilot.pause()
            assert app._phase == 'modes'
            app.action_back()
            await pilot.pause()
            assert app._phase == 'apps'

    @pytest.mark.asyncio
    async def test_direct_app_exits(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            # Simulate selecting the direct_app item
            lv = app.query_one('#app-list', ListView)
            item = lv.children[2]  # direct_app
            app.on_list_view_selected(ListView.Selected(lv, item, 2))
            await pilot.pause()
            assert app.return_value is not None
            assert app.return_value['app']['name'] == 'Direct'

    @pytest.mark.asyncio
    async def test_ask_form_shows_input(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            app._selected_app = apps['ask_app']
            app._resolve_mode('custom', apps['ask_app']['modes']['custom'])
            await pilot.pause()
            assert app._phase == 'ask'
            inp = app.query_one('#ask-msg')
            assert inp is not None


# ── Inline subprocess execution ──────────────────────────────────────────────

class TestInlineExecution:
    @pytest.mark.asyncio
    async def test_inline_creates_process_row(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            app._selected_app = apps['inline_app']
            app._run_inline([])
            await pilot.pause()
            assert len(app._processes) == 1
            row = app._processes[1]
            assert isinstance(row, ProcessRow)
            assert row.app_name == 'Inline'

    @pytest.mark.asyncio
    async def test_inline_returns_to_apps_phase(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            app._selected_app = apps['inline_app']
            app._run_inline([])
            await pilot.pause()
            assert app._phase == 'apps'

    @pytest.mark.asyncio
    async def test_inline_captures_output(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            app._selected_app = apps['inline_app']
            app._run_inline([])
            await asyncio.sleep(1)
            await pilot.pause()
            row = app._processes[1]
            assert len(row.log_lines) > 0
            assert any('line' in l for l in row.log_lines)

    @pytest.mark.asyncio
    async def test_multiple_inline_processes(self, tmp_path):
        apps = _make_apps(tmp_path)
        app = _TestApp(apps, tmp_path)
        async with app.run_test() as pilot:
            app._selected_app = apps['inline_app']
            app._run_inline([])
            await pilot.pause()
            app._selected_app = apps['multi_mode']
            app._run_inline([])
            await pilot.pause()
            assert len(app._processes) == 2


# ── run_task ─────────────────────────────────────────────────────────────────

def _dummy_task(*, log, steps=3):
    import time
    for i in range(1, steps + 1):
        log(f'step {i}')
        time.sleep(0.05)


def _failing_task(*, log):
    log('starting')
    raise RuntimeError('boom')


class TestRunTask:
    @pytest.mark.asyncio
    async def test_creates_process_row(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('My Task', _dummy_task, steps=2)
            await pilot.pause()
            assert proc_id == 1
            assert proc_id in app._processes
            row = app._processes[proc_id]
            assert row.app_name == 'My Task'

    @pytest.mark.asyncio
    async def test_captures_log_lines(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('Log Task', _dummy_task, steps=3)
            await asyncio.sleep(1)
            await pilot.pause()
            row = app._processes[proc_id]
            assert row.log_lines == ['step 1', 'step 2', 'step 3']

    @pytest.mark.asyncio
    async def test_spinner_stops_on_completion(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('Done Task', _dummy_task, steps=1)
            await asyncio.sleep(0.5)
            await pilot.pause()
            row = app._processes[proc_id]
            spinner = row.query_one(SpinnerIndicator)
            assert not spinner._active

    @pytest.mark.asyncio
    async def test_error_captured_in_log(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('Fail Task', _failing_task)
            await asyncio.sleep(0.5)
            await pilot.pause()
            row = app._processes[proc_id]
            assert any('Error' in l and 'boom' in l for l in row.log_lines)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_tasks(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            id1 = app.run_task('T1', _dummy_task, steps=2)
            id2 = app.run_task('T2', _dummy_task, steps=2)
            id3 = app.run_task('T3', _dummy_task, steps=2)
            await asyncio.sleep(1)
            await pilot.pause()
            assert len(app._processes) == 3
            for pid in (id1, id2, id3):
                assert len(app._processes[pid].log_lines) == 2

    @pytest.mark.asyncio
    async def test_returns_incrementing_ids(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            id1 = app.run_task('A', _dummy_task, steps=1)
            id2 = app.run_task('B', _dummy_task, steps=1)
            assert id1 == 1
            assert id2 == 2

    @pytest.mark.asyncio
    async def test_debug_logging(self, tmp_path, caplog):
        app = _TestApp({}, tmp_path)
        with caplog.at_level('DEBUG', logger='gppu.tui.launcher'):
            async with app.run_test() as pilot:
                app.run_task('Logged', _dummy_task, steps=2)
                await asyncio.sleep(0.5)
                await pilot.pause()
        assert any('[Logged] step 1' in r.message for r in caplog.records)
        assert any('[Logged] step 2' in r.message for r in caplog.records)


# ── Log panel / show_process_logs ────────────────────────────────────────────

class TestLogPanel:
    @pytest.mark.asyncio
    async def test_show_populates_panel(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('Panel', _dummy_task, steps=2)
            await asyncio.sleep(0.5)
            await pilot.pause()
            app.show_process_logs(proc_id)
            await pilot.pause()
            panel = app.query_one('#output-panel', RichLog)
            assert panel.has_class('visible')
            assert app._active_log == proc_id

    @pytest.mark.asyncio
    async def test_toggle_hides_panel(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('Toggle', _dummy_task, steps=1)
            await asyncio.sleep(0.5)
            await pilot.pause()
            app.show_process_logs(proc_id)
            await pilot.pause()
            app.show_process_logs(proc_id)
            await pilot.pause()
            panel = app.query_one('#output-panel', RichLog)
            assert not panel.has_class('visible')
            assert app._active_log is None

    @pytest.mark.asyncio
    async def test_switch_between_processes(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            id1 = app.run_task('A', _dummy_task, steps=2)
            id2 = app.run_task('B', _dummy_task, steps=2)
            await asyncio.sleep(1)
            await pilot.pause()
            app.show_process_logs(id1)
            await pilot.pause()
            assert app._active_log == id1
            assert app._processes[id1].has_class('active-log')
            app.show_process_logs(id2)
            await pilot.pause()
            assert app._active_log == id2
            assert app._processes[id2].has_class('active-log')
            assert not app._processes[id1].has_class('active-log')

    @pytest.mark.asyncio
    async def test_action_toggle_output_key(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('O key', _dummy_task, steps=1)
            await asyncio.sleep(0.5)
            await pilot.pause()
            await pilot.press('o')
            await pilot.pause()
            panel = app.query_one('#output-panel', RichLog)
            assert panel.has_class('visible')
            assert app._active_log == proc_id
            await pilot.press('o')
            await pilot.pause()
            assert not panel.has_class('visible')

    @pytest.mark.asyncio
    async def test_escape_hides_panel(self, tmp_path):
        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('Esc', _dummy_task, steps=1)
            await asyncio.sleep(0.5)
            await pilot.pause()
            app.show_process_logs(proc_id)
            await pilot.pause()
            assert app.query_one('#output-panel', RichLog).has_class('visible')
            await pilot.press('escape')
            await pilot.pause()
            assert not app.query_one('#output-panel', RichLog).has_class('visible')
            assert app._active_log is None

    @pytest.mark.asyncio
    async def test_live_append_while_viewing(self, tmp_path):
        import time

        def slow_task(*, log):
            log('first')
            time.sleep(0.3)
            log('second')

        app = _TestApp({}, tmp_path)
        async with app.run_test() as pilot:
            proc_id = app.run_task('Live', slow_task)
            await asyncio.sleep(0.1)
            await pilot.pause()
            app.show_process_logs(proc_id)
            await pilot.pause()
            lines_before = len(app._processes[proc_id].log_lines)
            await asyncio.sleep(0.5)
            await pilot.pause()
            assert len(app._processes[proc_id].log_lines) > lines_before
