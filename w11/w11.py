"""
w11 — Windows 11 Superapp launcher.

Opens w11 sub-apps (events, onedrive, etc.) from a single TUI menu.
Each app declares a manifest in its own YAML config describing modes and launch args.

Usage:
    python w11.py                  # interactive TUI launcher
    python w11.py events           # launch w11_events directly
    python w11.py onedrive         # launch w11-onedrive directly
    python w11.py --list           # list available apps
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from gppu import Env, dict_from_yml
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual import work
from textual.widgets import Footer, Header, Input, ListItem, ListView, OptionList, RichLog, Static

# ── Config ───────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).parent


def load_apps() -> dict[str, dict]:
    """Load app registry via Env, then read each app's manifest + config via dict_from_yml."""
    # Env(name='w11', app_path=Path('RAN/Win11'))
    Env()
    Env.load()
    registry = Env.glob_dict('apps')
    apps: dict[str, dict] = {}
    for key, config_file in registry.items():
        cfg = dict_from_yml(APP_DIR / config_file)
        manifest = cfg.get('manifest', {})
        if manifest:
            manifest['_config'] = {k: v for k, v in cfg.items() if k != 'manifest'}
            apps[key] = manifest
    return apps


# ── Launch ───────────────────────────────────────────────────────────────────

def build_args(mode_def: dict | None) -> list[str]:
    """Build CLI args from a mode definition."""
    if not mode_def:
        return []
    return list(mode_def.get('args', []) or [])


def launch_app(app_def: dict, extra_args: list[str] | None = None) -> None:
    """Launch a sub-app by running its script in a new process."""
    script = APP_DIR / app_def['script']
    if not script.exists():
        print(f'Script not found: {script}')
        sys.exit(1)
    cmd = [sys.executable, str(script)] + (extra_args or [])
    subprocess.run(cmd)


# ── TUI ──────────────────────────────────────────────────────────────────────

class AppItem(ListItem):
    """A selectable app entry."""

    def __init__(self, key: str, app_def: dict) -> None:
        super().__init__()
        self.app_key = key
        self.app_def = app_def

    def compose(self) -> ComposeResult:
        icon = self.app_def.get('icon', '')
        name = self.app_def.get('name', self.app_key)
        desc = self.app_def.get('description', '')
        yield Static(f' {icon}  [bold]{name}[/bold]   [dim]{desc}[/dim]')


class ModeItem(ListItem):
    """A selectable mode entry."""

    def __init__(self, mode_key: str, mode_def: dict | None) -> None:
        super().__init__()
        self.mode_key = mode_key
        self.mode_def = mode_def or {}

    def compose(self) -> ComposeResult:
        label = self.mode_def.get('name', self.mode_key)
        yield Static(f'  {label}')


class SpinnerIndicator(Static):
    """Animated spinner indicating a background process is running.

    Click to toggle the full output panel.
    """

    FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    def __init__(self, **kwargs) -> None:
        super().__init__('', **kwargs)
        self._frame = 0
        self._active = False
        self._timer = None

    def start(self) -> None:
        self._active = True
        if self._timer:
            self._timer.stop()
        self._timer = self.set_interval(1 / 12, self._tick)

    def stop(self) -> None:
        self._active = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        self.update('[green]✓[/green]')

    def reset(self) -> None:
        self._active = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        self.update('')

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(self.FRAMES)
        self.update(f'[yellow]{self.FRAMES[self._frame]}[/yellow]')

    def on_click(self) -> None:
        self.app.action_toggle_output()


class W11App(App):
    """Windows 11 Superapp launcher."""

    TITLE = 'w11'
    CSS = """
    Screen {
        align: center middle;
    }
    #top-bar {
        dock: top;
        height: 1;
        padding: 0 1;
        display: none;
    }
    #top-bar.has-process {
        display: block;
    }
    #spinner {
        width: 3;
        height: 1;
        min-width: 3;
    }
    #process-status {
        height: 1;
        width: 1fr;
    }
    #output-panel {
        dock: top;
        display: none;
        height: auto;
        max-height: 14;
        border-top: solid $primary;
        overflow-y: auto;
        padding: 0 1;
    }
    #output-panel.visible {
        display: block;
    }
    #menu {
        width: 80;
        max-height: 24;
        border: solid $primary;
        padding: 1 2;
    }
    #menu-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }
    ListView {
        height: auto;
    }
    ListItem {
        padding: 0;
    }
    ListItem > Static {
        width: 100%;
    }
    Input {
        border: none;
        padding: 0 1;
        height: 1;
    }
    Input:focus {
        border: none;
    }
    OptionList {
        height: auto;
        border: none;
        padding: 0;
    }
    OptionList:focus {
        border: none;
    }
    """
    BINDINGS = [
        Binding('q', 'quit', 'Quit'),
        Binding('escape', 'back', 'Back'),
        Binding('enter', 'launch', 'Launch', show=False),
        Binding('d', 'toggle_dark', 'Dark/Light'),
        Binding('o', 'toggle_output', 'Output', show=False),
    ]

    def __init__(self, apps: dict[str, dict]) -> None:
        super().__init__()
        self._apps = apps
        self._selected_app: dict | None = None
        self._phase = 'apps'  # apps → modes → ask
        self._bg_running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id='top-bar'):
            yield SpinnerIndicator(id='spinner')
            yield Static('', id='process-status')
        yield RichLog(id='output-panel')
        with Vertical(id='menu'):
            yield Static('Windows 11 Tools', id='menu-title')
            yield ListView(
                *[AppItem(k, v) for k, v in self._apps.items()],
                id='app-list',
            )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if self._phase == 'apps':
            item: AppItem = event.item  # type: ignore[assignment]
            self._selected_app = item.app_def
            modes = item.app_def.get('modes')
            if not modes:
                self.exit(result={'app': item.app_def, 'args': []})
            elif len(modes) == 1:
                mode_key = next(iter(modes))
                self._resolve_mode(mode_key, modes[mode_key])
            else:
                self._show_modes(item.app_def, modes)
        elif self._phase == 'modes':
            mode_item: ModeItem = event.item  # type: ignore[assignment]
            self._resolve_mode(mode_item.mode_key, mode_item.mode_def)

    def _show_modes(self, app_def: dict, modes: dict) -> None:
        self._phase = 'modes'
        title = self.query_one('#menu-title', Static)
        title.update(f'{app_def.get("name", "")} — Select Mode')
        lv = self.query_one('#app-list', ListView)
        lv.clear()
        for mk, md in modes.items():
            lv.append(ModeItem(mk, md))

    def _resolve_mode(self, mode_key: str, mode_def: dict | None) -> None:
        mode_def = mode_def or {}
        base_args = build_args(mode_def)
        ask_for = mode_def.get('ask_for')
        if ask_for:
            self._show_ask_form(ask_for, base_args)
        elif mode_def.get('inline'):
            self._run_inline(base_args)
        else:
            self.exit(result={'app': self._selected_app, 'args': base_args})

    def _run_inline(self, cli_args: list[str]) -> None:
        """Start a background process, show spinner + status in top bar."""
        self._bg_running = True
        app_name = self._selected_app.get('name', '')

        # Show top bar
        top_bar = self.query_one('#top-bar')
        top_bar.add_class('has-process')

        # Start spinner
        spinner = self.query_one('#spinner', SpinnerIndicator)
        spinner.start()

        # Update status
        status = self.query_one('#process-status', Static)
        status.update(f' [bold]{app_name}[/bold] [dim]running…[/dim]')

        # Clear previous output
        log = self.query_one('#output-panel', RichLog)
        log.clear()

        # Return to apps list so user can keep navigating
        self._phase = 'apps'
        self._run_inline_cmd(cli_args, app_name)

    @work(thread=True)
    def _run_inline_cmd(self, cli_args: list[str], app_name: str) -> None:
        script = APP_DIR / self._selected_app['script']
        cmd = [sys.executable, '-u', str(script)] + cli_args
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                line = line.rstrip('\n\r')
                if line:
                    self.call_from_thread(self._append_output, line)
            proc.wait()
        except Exception as e:
            self.call_from_thread(self._append_output, f'Error: {e}')
        self.call_from_thread(self._process_done, app_name)

    def _append_output(self, line: str) -> None:
        """Append a line to the output panel and update the status indicator."""
        log = self.query_one('#output-panel', RichLog)
        log.write(line)
        status = self.query_one('#process-status', Static)
        # Show truncated last line as the static indicator
        display = line if len(line) <= 70 else line[:67] + '…'
        status.update(f' [dim]{display}[/dim]')

    def _process_done(self, app_name: str) -> None:
        """Called when the background process finishes."""
        self._bg_running = False
        spinner = self.query_one('#spinner', SpinnerIndicator)
        spinner.stop()
        status = self.query_one('#process-status', Static)
        status.update(f' [bold]{app_name}[/bold] [green]done[/green]  [dim]click ✓ or press O for output[/dim]')

    def action_toggle_output(self) -> None:
        """Toggle the output panel visibility."""
        panel = self.query_one('#output-panel', RichLog)
        panel.toggle_class('visible')

    def _show_ask_form(self, fields: list, base_args: list[str] | None = None) -> None:
        self._phase = 'ask'
        self._base_args = base_args or []
        self._ask_fields: list[dict] = []

        app_config = self._selected_app.get('_config', {})
        title = self.query_one('#menu-title', Static)
        title.update(f'{self._selected_app.get("name", "")} — Parameters  [dim]Enter=Launch[/dim]')
        lv = self.query_one('#app-list', ListView)
        lv.display = False

        menu = self.query_one('#menu')
        for field_spec in fields:
            if isinstance(field_spec, str):
                field_spec = {'name': field_spec}
            self._ask_fields.append(field_spec)
            fname = field_spec['name']
            default = field_spec.get('default', app_config.get(fname, ''))
            default = str(default) if default is not None else ''
            options = field_spec.get('options')
            # Resolve options from app config if it's a string key reference
            if isinstance(options, str):
                options = app_config.get(options) or []

            menu.mount(Static(f'{fname}:'))
            if options:
                ol = OptionList(*[str(o) for o in options], id=f'ask-{fname}')
                menu.mount(ol)
                # Pre-highlight the default value
                for i, o in enumerate(options):
                    if str(o) == default:
                        ol.highlighted = i
                        break
            else:
                menu.mount(Input(value=default, placeholder=fname,
                                 id=f'ask-{fname}'))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Auto-launch when an OptionList item is selected (Enter/click)."""
        if self._phase == 'ask':
            self.action_launch()

    def action_launch(self) -> None:
        if self._phase != 'ask':
            return
        args: list[str] = list(self._base_args)
        for field_spec in self._ask_fields:
            fname = field_spec['name']
            widget = self.query_one(f'#ask-{fname}')
            if isinstance(widget, OptionList):
                opt = widget.get_option_at_index(widget.highlighted)
                val = str(opt.prompt) if opt else ''
            else:
                val = widget.value.strip()
            if val:
                args.extend([f'--{fname}', val])
        self.exit(result={'app': self._selected_app, 'args': args})

    def action_back(self) -> None:
        if self._phase == 'apps':
            # Hide output panel if visible, otherwise quit
            panel = self.query_one('#output-panel', RichLog)
            if panel.has_class('visible'):
                panel.remove_class('visible')
                return
            self.exit(result=None)
            return
        # Clean up phase-specific widgets
        if self._phase == 'ask':
            menu = self.query_one('#menu')
            for widget in list(menu.children):
                if widget.id and widget.id.startswith('ask-'):
                    widget.remove()
                elif isinstance(widget, (Input, OptionList, Static)) and widget.id not in ('menu-title', 'app-list'):
                    widget.remove()
            lv = self.query_one('#app-list', ListView)
            lv.display = True
        # Reset to app list
        self._phase = 'apps'
        self._selected_app = None
        title = self.query_one('#menu-title', Static)
        title.update('Windows 11 Tools')
        lv = self.query_one('#app-list', ListView)
        lv.clear()
        for k, v in self._apps.items():
            lv.append(AppItem(k, v))


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    apps = load_apps()

    parser = argparse.ArgumentParser(description='w11 — Windows 11 Superapp')
    parser.add_argument('app', nargs='?', default=None,
                        choices=list(apps.keys()),
                        help='App to launch directly')
    parser.add_argument('--list', action='store_true',
                        help='List available apps and exit')
    parser.add_argument('extra', nargs=argparse.REMAINDER,
                        help='Extra arguments passed to the sub-app')
    args = parser.parse_args()

    if args.list:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        for key, app_def in apps.items():
            icon = app_def.get('icon', '')
            name = app_def.get('name', key)
            desc = app_def.get('description', '')
            print(f'  {icon}  {key:12s}  {name} — {desc}')
        return

    # Direct launch
    if args.app:
        launch_app(apps[args.app], args.extra or None)
        return

    # TUI launcher — loop back after sub-app exits
    while True:
        tui = W11App(apps)
        result = tui.run()
        if not result:
            break
        launch_app(result['app'], result.get('args') or None)


if __name__ == '__main__':
    main()
