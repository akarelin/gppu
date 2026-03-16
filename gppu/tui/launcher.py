"""Reusable TUI superapp launcher framework.

Provides a Textual-based menu for launching sub-apps defined via YAML manifests.
Each consumer creates a thin wrapper with its own Env initialization and branding.

Usage::

    from gppu import Env
    from gppu.tui import LauncherApp, launcher_main, load_app_registry

    class MyApp(LauncherApp):
        TITLE = 'My Tools'
        MENU_TITLE = 'My Tools'

    def main():
        Env(name='myapp', app_path=APP_DIR)
        Env.load()
        apps = load_app_registry(APP_DIR)
        launcher_main(apps, MyApp, APP_DIR, 'My Tools — launcher')
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from gppu import Env, dict_from_yml
from textual.app import App, ComposeResult, RenderResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.dom import NoScreen
from textual.events import Mount
from textual import work
from textual.widgets import (
    Footer, Header, Input, ListItem, ListView, OptionList, RichLog, Static,
)
from textual.widgets._header import HeaderIcon, HeaderTitle


# ── StatusHeader ──────────────────────────────────────────────────────────────

class _HeaderIndicator(Static):
    """Right-aligned indicator area replacing Textual's empty HeaderClockSpace."""

    DEFAULT_CSS = """
    _HeaderIndicator {
        dock: right;
        width: auto;
        max-width: 60%;
        padding: 0 1;
        content-align: right middle;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        color: $foreground;
        text-opacity: 85%;
    }
    """


class StatusHeader(Header):
    """Header that shows ``sub_title`` right-aligned instead of center-merged.

    Drop-in replacement for Textual's ``Header``.  The title stays centered;
    the subtitle (set via ``app.sub_title``) renders on the right where
    Textual < 1.0 used to place it.
    """

    def compose(self) -> ComposeResult:
        yield HeaderIcon().data_bind(StatusHeader.icon)
        yield HeaderTitle()
        yield _HeaderIndicator()

    def format_title(self) -> Content:
        """Title only — sub_title is handled by the right indicator."""
        return Content(self.screen_title)

    def _on_mount(self, _: Mount) -> None:
        async def set_title() -> None:
            try:
                self.query_one(HeaderTitle).update(self.format_title())
            except NoScreen:
                pass

        async def set_indicator() -> None:
            try:
                sub = self.screen_sub_title
                indicator = self.query_one(_HeaderIndicator)
                indicator.update(f'[dim]{sub}[/dim]' if sub else '')
            except NoScreen:
                pass

        self.watch(self.app, 'title', set_title)
        self.watch(self.screen, 'title', set_title)
        self.watch(self.app, 'sub_title', set_indicator)
        self.watch(self.screen, 'sub_title', set_indicator)


# ── Utilities ────────────────────────────────────────────────────────────────

def build_args(mode_def: dict | None) -> list[str]:
    """Build CLI args from a mode definition."""
    if not mode_def:
        return []
    return list(mode_def.get('args', []) or [])


def resolve_cwd(app_dir: Path, app_def: dict) -> Path:
    """Resolve working directory for a sub-app.

    Uses the ``cwd`` key from the manifest if present, otherwise defaults
    to the parent directory of the script.
    """
    if 'cwd' in app_def:
        return (app_dir / app_def['cwd']).resolve()
    return (app_dir / app_def['script']).resolve().parent


def _resolve_cmd(app_dir: Path, app_def: dict) -> list[str]:
    """Build the command to launch a sub-app, handling frozen (PyInstaller) mode."""
    if getattr(sys, 'frozen', False):
        exe_name = Path(app_def['script']).stem + '.exe'
        exe = Path(sys.executable).parent / exe_name
        if not exe.exists():
            print(f'Executable not found: {exe}')
            sys.exit(1)
        return [str(exe)]
    script = (app_dir / app_def['script']).resolve()
    if not script.exists():
        print(f'Script not found: {script}')
        sys.exit(1)
    return [sys.executable, str(script)]


def launch_app(
    app_dir: Path, app_def: dict, extra_args: list[str] | None = None,
) -> None:
    """Launch a sub-app by running its script in a new process."""
    cmd = _resolve_cmd(app_dir, app_def) + (extra_args or [])
    subprocess.run(cmd, cwd=resolve_cwd(app_dir, app_def))


def load_app_registry(app_dir: Path) -> dict[str, dict]:
    """Load app manifests from YAML configs referenced in ``Env.glob_dict('apps')``.

    Call ``Env()`` + ``Env.load()`` before this.
    """
    registry = Env.glob_dict('apps')
    apps: dict[str, dict] = {}
    for key, config_file in registry.items():
        cfg = dict_from_yml(app_dir / config_file)
        manifest = cfg.get('manifest', {})
        if manifest:
            manifest['_config'] = {k: v for k, v in cfg.items() if k != 'manifest'}
            apps[key] = manifest
    return apps


# ── Widgets ──────────────────────────────────────────────────────────────────

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


# ── Base Launcher App ────────────────────────────────────────────────────────

class LauncherApp(App):
    """Base TUI superapp launcher.

    Subclass and set ``TITLE`` / ``MENU_TITLE``, then pass to
    :func:`launcher_main`.
    """

    TITLE = 'Launcher'
    MENU_TITLE = 'Apps'

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

    def __init__(self, apps: dict[str, dict], app_dir: Path) -> None:
        super().__init__()
        self._apps = apps
        self._app_dir = app_dir
        self._selected_app: dict | None = None
        self._phase = 'apps'  # apps → modes → ask
        self._bg_running = False

    def compose(self) -> ComposeResult:
        yield StatusHeader()
        with Horizontal(id='top-bar'):
            yield SpinnerIndicator(id='spinner')
            yield Static('', id='process-status')
        yield RichLog(id='output-panel')
        with Vertical(id='menu'):
            yield Static(self.MENU_TITLE, id='menu-title')
            yield ListView(
                *[AppItem(k, v) for k, v in self._apps.items()],
                id='app-list',
            )
        yield Footer()

    # ── App / mode selection ─────────────────────────────────────────────

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

    # ── Inline / background execution ────────────────────────────────────

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
        cmd = _resolve_cmd(self._app_dir, self._selected_app)
        if not getattr(sys, 'frozen', False):
            cmd.insert(1, '-u')
        cmd += cli_args
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                cwd=resolve_cwd(self._app_dir, self._selected_app),
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
        display = line if len(line) <= 70 else line[:67] + '…'
        status.update(f' [dim]{display}[/dim]')

    def _process_done(self, app_name: str) -> None:
        """Called when the background process finishes."""
        self._bg_running = False
        spinner = self.query_one('#spinner', SpinnerIndicator)
        spinner.stop()
        status = self.query_one('#process-status', Static)
        status.update(
            f' [bold]{app_name}[/bold] [green]done[/green]'
            f'  [dim]click ✓ or press O for output[/dim]'
        )

    def action_toggle_output(self) -> None:
        """Toggle the output panel visibility."""
        panel = self.query_one('#output-panel', RichLog)
        panel.toggle_class('visible')

    # ── Ask form ─────────────────────────────────────────────────────────

    def _show_ask_form(
        self, fields: list, base_args: list[str] | None = None,
    ) -> None:
        self._phase = 'ask'
        self._base_args = base_args or []
        self._ask_fields: list[dict] = []

        app_config = self._selected_app.get('_config', {})
        title = self.query_one('#menu-title', Static)
        title.update(
            f'{self._selected_app.get("name", "")} — Parameters'
            f'  [dim]Enter=Launch[/dim]'
        )
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
                ol = OptionList(
                    *[str(o) for o in options], id=f'ask-{fname}',
                )
                menu.mount(ol)
                # Pre-highlight the default value
                for i, o in enumerate(options):
                    if str(o) == default:
                        ol.highlighted = i
                        break
            else:
                menu.mount(Input(
                    value=default, placeholder=fname, id=f'ask-{fname}',
                ))

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected,
    ) -> None:
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

    # ── Navigation ───────────────────────────────────────────────────────

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
                elif isinstance(widget, (Input, OptionList, Static)) \
                        and widget.id not in ('menu-title', 'app-list'):
                    widget.remove()
            lv = self.query_one('#app-list', ListView)
            lv.display = True
        # Reset to app list
        self._phase = 'apps'
        self._selected_app = None
        title = self.query_one('#menu-title', Static)
        title.update(self.MENU_TITLE)
        lv = self.query_one('#app-list', ListView)
        lv.clear()
        for k, v in self._apps.items():
            lv.append(AppItem(k, v))


# ── CLI entrypoint ───────────────────────────────────────────────────────────

def launcher_main(
    apps: dict[str, dict],
    app_class: type[LauncherApp],
    app_dir: Path,
    description: str = 'TUI Launcher',
) -> None:
    """Parse CLI args and run the TUI loop.

    Call after ``Env.load()`` and ``load_app_registry()``.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        'app', nargs='?', default=None,
        choices=list(apps.keys()),
        help='App to launch directly',
    )
    parser.add_argument(
        '--list', action='store_true',
        help='List available apps and exit',
    )
    parser.add_argument(
        'extra', nargs=argparse.REMAINDER,
        help='Extra arguments passed to the sub-app',
    )
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
        launch_app(app_dir, apps[args.app], args.extra or None)
        return

    # TUI launcher — loop back after sub-app exits
    while True:
        tui = app_class(apps, app_dir)
        result = tui.run()
        if not result:
            break
        launch_app(app_dir, result['app'], result.get('args') or None)
