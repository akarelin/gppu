#!/usr/bin/env python3
"""Demo showcasing all gppu.tui features.

Run:  python examples/tui_demo.py

Features demonstrated:
  - Multiple concurrent inline processes with individual spinners
  - run_task() — async Python callable with spinner + debug log capture
  - Click any process row to view its logs (click again to hide)
  - Press 'o' to toggle logs for the most recent process
  - Mode selection (single-mode auto-selects, multi-mode shows picker)
  - Ask form with text inputs and option lists
  - Direct launch (exits TUI, runs in terminal, returns)
  - Dark/light toggle ('d'), back ('Esc'), quit ('q')
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import textwrap
from pathlib import Path

from gppu.tui import LauncherApp, launch_app

# ── Create temporary sub-app scripts ────────────────────────────────────────

_tmpdir = Path(tempfile.mkdtemp(prefix='gppu_tui_demo_'))
atexit.register(shutil.rmtree, _tmpdir, ignore_errors=True)

(_tmpdir / 'counter.py').write_text(textwrap.dedent("""\
    import sys, time
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    for i in range(1, n + 1):
        print(f"[{i}/{n}] Processing batch...")
        time.sleep(0.8)
    print("Counter finished.")
"""))

(_tmpdir / 'fast_log.py').write_text(textwrap.dedent("""\
    import time
    for i in range(30):
        print(f"  [{i:03d}] fast log line — sensor_id=A{i % 4} value={i * 3.7:.1f}")
        time.sleep(0.15)
    print("Fast logger done.")
"""))

(_tmpdir / 'echo.py').write_text(textwrap.dedent("""\
    import sys
    print(f"Received args: {sys.argv[1:]}")
    input("Press Enter to return to launcher...")
"""))

(_tmpdir / 'greeting.py').write_text(textwrap.dedent("""\
    import sys
    name = "world"
    fmt = "text"
    args = sys.argv[1:]
    while args:
        if args[0] == "--name" and len(args) > 1:
            name = args[1]; args = args[2:]
        elif args[0] == "--format" and len(args) > 1:
            fmt = args[1]; args = args[2:]
        else:
            args = args[1:]
    if fmt == "json":
        print(f'{{"greeting": "Hello, {name}!"}}')
    elif fmt == "yaml":
        print(f"greeting: Hello, {name}!")
    else:
        print(f"Hello, {name}!")
    input("Press Enter to return...")
"""))

# ── App registry ────────────────────────────────────────────────────────────

APPS: dict[str, dict] = {
    'counter': {
        'name': 'Slow Counter',
        'icon': '\U0001f522',
        'description': 'Background counter with spinner (inline subprocess)',
        'script': 'counter.py',
        'modes': {
            'short': {'name': '5 steps',  'args': ['5'],  'inline': True},
            'long':  {'name': '15 steps', 'args': ['15'], 'inline': True},
        },
    },
    'fast_log': {
        'name': 'Fast Logger',
        'icon': '\U0001f4dd',
        'description': 'Rapid log output (inline subprocess, single mode)',
        'script': 'fast_log.py',
        'modes': {
            'run': {'name': 'Run', 'inline': True},
        },
    },
    'data_sync': {
        'name': 'Data Sync (run_task)',
        'icon': '\u26a1',
        'description': 'Python callable via run_task() + debug log',
    },
    'multi_task': {
        'name': 'Multi Task (run_task x3)',
        'icon': '\U0001f500',
        'description': 'Launches 3 concurrent tasks at once',
    },
    'greeting': {
        'name': 'Greeting',
        'icon': '\U0001f44b',
        'description': 'Ask-form demo with inputs & option list',
        'script': 'greeting.py',
        'modes': {
            'custom': {
                'name': 'Custom greeting',
                'ask_for': [
                    {'name': 'name', 'default': 'World'},
                    {'name': 'format', 'options': ['text', 'json', 'yaml']},
                ],
            },
        },
    },
    'echo': {
        'name': 'Echo (direct)',
        'icon': '\U0001f50a',
        'description': 'Direct launch — exits TUI, runs in terminal',
        'script': 'echo.py',
    },
}

# ── Demo app ────────────────────────────────────────────────────────────────


def _simulate_sync(*, log, steps=8):
    """Example task callable — receives ``log`` from run_task."""
    import time
    for i in range(1, steps + 1):
        log(f'Step {i}/{steps}: syncing records batch...')
        time.sleep(0.6)
    log('All batches synced successfully.')


def _simulate_worker(*, log, worker_id, items=6):
    import time
    for i in range(1, items + 1):
        log(f'[W{worker_id}] item {i}/{items}')
        time.sleep(0.4 + worker_id * 0.15)
    log(f'[W{worker_id}] finished')


class DemoApp(LauncherApp):
    TITLE = 'gppu.tui Demo'
    MENU_TITLE = '\U0001f3aa  Feature Demo'

    def on_list_view_selected(self, event):
        if self._phase == 'apps':
            item = event.item
            if hasattr(item, 'app_key') and item.app_key == 'data_sync':
                self.run_task('Data Sync', _simulate_sync, steps=10)
                return
            if hasattr(item, 'app_key') and item.app_key == 'multi_task':
                for wid in range(1, 4):
                    self.run_task(f'Worker {wid}', _simulate_worker, worker_id=wid)
                return
        super().on_list_view_selected(event)


def main() -> None:
    while True:
        tui = DemoApp(APPS, _tmpdir)
        result = tui.run()
        if not result:
            break
        launch_app(_tmpdir, result['app'], result.get('args') or None)


if __name__ == '__main__':
    main()
