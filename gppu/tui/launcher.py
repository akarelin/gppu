"""Reusable TUI superapp launcher framework.

Provides a Textual-based menu for launching sub-apps defined via YAML manifests.
Each consumer creates a thin wrapper with its own Env initialization and branding.

Usage::

    from gppu import Env
    from gppu.tui import TUILauncher, launcher_main, load_app_registry

    class MyApp(TUILauncher):
        TITLE = 'My Tools'
        MENU_TITLE = 'My Tools'

    def main():
        Env.from_env(name='myapp', app_path=APP_DIR)
        apps = load_app_registry(APP_DIR)
        launcher_main(apps, MyApp, APP_DIR, 'My Tools — launcher')

    # Serve as a web app:  python myapp.py --serve [--port 8566] [--host localhost]
"""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

from gppu import Env, App, mixin_Config, dict_from_yml
from gppu.gppu import OSType
from textual.app import App as TextualApp, ComposeResult
from textual.binding import Binding
from textual.command import Hit, Hits, Provider
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.dom import NoScreen
from textual.events import Mount
from textual import work
from textual.screen import Screen
from textual.widgets import (
    Footer, Header, Input, ListItem, ListView, OptionList, RichLog, Static,
)
from textual.widgets._header import HeaderIcon, HeaderTitle

_log = logging.getLogger(__name__)


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


def _platform_spec(d: dict | None) -> list[str]:
    """Read the manifest 'platform:' key as a normalized list of OSType names.

    Empty list ⇒ no restriction (all platforms allowed).
    """
    if not d:
        return []
    spec = d.get('platform')
    if spec is None or spec == '':
        return []
    if isinstance(spec, str):
        spec = [spec]
    return [str(s).upper() for s in spec]


def platform_ok(d: dict | None, current_os: OSType | None = None) -> bool:
    """True if `d['platform']` permits running on the current OS."""
    spec = _platform_spec(d)
    if not spec:
        return True
    cur = (current_os or Env.os).name.upper()
    return cur in spec


def _platform_label(d: dict | None) -> str:
    """Render 'platform:' for a help/list suffix; empty string if unrestricted."""
    spec = _platform_spec(d)
    return ', '.join(spec) if spec else ''


def _script_for_os(app_def: dict) -> str:
    """Return the platform-specific script path from a manifest.

    `script:` may be a string (single path) or a dict keyed by OSType name
    (e.g. ``W11: ...``, ``LINUX: ...``).  When dict, the current OS is looked
    up; falls back to a ``default:`` entry if present.
    """
    script = app_def.get('script')
    if isinstance(script, dict):
        cur = Env.os.name.upper()
        if cur in script:
            return script[cur]
        for k in script:
            if k.upper() == cur:
                return script[k]
        if 'default' in script:
            return script['default']
        raise KeyError(
            f"Manifest 'script' has no entry for {cur}; "
            f"keys: {list(script.keys())}"
        )
    return script


def resolve_cwd(app_dir: Path, app_def: dict) -> Path:
    """Resolve working directory for a sub-app.

    Uses the ``cwd`` key from the manifest if present, otherwise defaults
    to the parent directory of the script.
    """
    if 'cwd' in app_def:
        return (app_dir / app_def['cwd']).resolve()
    return (app_dir / _script_for_os(app_def)).resolve().parent


def _resolve_cmd(app_dir: Path, app_def: dict) -> list[str]:
    """Build the command to launch a sub-app, handling frozen (PyInstaller) mode."""
    script_str = _script_for_os(app_def)
    if getattr(sys, 'frozen', False):
        exe_name = Path(script_str).stem + '.exe'
        exe = Path(sys.executable).parent / exe_name
        if not exe.exists():
            print(f'Executable not found: {exe}')
            sys.exit(1)
        return [str(exe)]
    script = (app_dir / script_str).resolve()
    if not script.exists():
        print(f'Script not found: {script}')
        sys.exit(1)
    if script.suffix.lower() == '.exe':
        return [str(script)]
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
        self.enabled = platform_ok(app_def)
        if not self.enabled:
            self.add_class('platform-disabled')

    def compose(self) -> ComposeResult:
        icon = self.app_def.get('icon', '')
        name = self.app_def.get('name', self.app_key)
        desc = self.app_def.get('description', '')
        if self.enabled:
            yield Static(f' {icon}  [bold]{name}[/bold]   [dim]{desc}[/dim]')
        else:
            plat = _platform_label(self.app_def)
            yield Static(
                f' [dim]{icon}  {name}[/]   '
                f'[dim italic]({plat} only — current: {Env.os.name})[/]'
            )


class ModeItem(ListItem):
    """A selectable mode entry."""

    def __init__(self, mode_key: str, mode_def: dict | None,
                 app_def: dict | None = None) -> None:
        super().__init__()
        self.mode_key = mode_key
        self.mode_def = mode_def or {}
        # Mode-level platform overrides app-level; otherwise inherit app-level.
        if 'platform' in self.mode_def:
            self.enabled = platform_ok(self.mode_def)
            self._effective_platform = self.mode_def
        else:
            self.enabled = platform_ok(app_def or {})
            self._effective_platform = app_def or {}
        if not self.enabled:
            self.add_class('platform-disabled')

    def compose(self) -> ComposeResult:
        label = self.mode_def.get('name', self.mode_key)
        if self.enabled:
            yield Static(f'  {label}')
        else:
            plat = _platform_label(self._effective_platform)
            yield Static(
                f'  [dim]{label}   [italic]({plat} only)[/][/]'
            )


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



class InfoScreen(Screen):
    """Modal screen showing Env config as sections."""

    BINDINGS = [
        Binding('escape', 'dismiss', 'Back', show=False),
        Binding('i', 'dismiss', 'Close', show=False),
        Binding('q', 'dismiss', 'Close', show=False),
    ]

    CSS = """
    #info-panel {
        width: 80%;
        height: 80%;
        border: round $primary;
        padding: 1 2;
        background: $boost;
    }
    """

    def __init__(self, sections: list[tuple[str, str]]) -> None:
        super().__init__()
        self._sections = sections

    def compose(self) -> ComposeResult:
        yield RichLog(id='info-panel', markup=True)

    def on_mount(self) -> None:
        panel = self.query_one('#info-panel', RichLog)
        for i, (heading, body) in enumerate(self._sections):
            if i > 0:
                panel.write('')
            panel.write(f'[bold underline]{heading}[/bold underline]')
            for line in body.splitlines():
                panel.write(f'  {line}')

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class ProcessRow(Horizontal):
    """A row in the process bar representing one background process.

    Click to toggle that process's log output in the shared output panel.
    """

    def __init__(self, proc_id: int, app_name: str) -> None:
        super().__init__(id=f'proc-{proc_id}', classes='process-row')
        self.proc_id = proc_id
        self.app_name = app_name
        self.log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield SpinnerIndicator(classes='proc-spinner')
        yield Static(
            f' [bold]{self.app_name}[/bold] [dim]running…[/dim]',
            classes='proc-status',
        )
        yield Static(' [dim]▸ logs[/dim]', classes='log-toggle')

    def on_mount(self) -> None:
        self.query_one(SpinnerIndicator).start()

    def on_click(self) -> None:
        self.app.show_process_logs(self.proc_id)


# ── Base TUI App Classes ─────────────────────────────────────────────────────

def _tui_available() -> bool:
  """Check if a TUI can be displayed (textual installed + interactive terminal or web serve)."""
  try:
    import textual  # noqa
  except ImportError:
    return False
  # textual-serve runs without a real TTY but sets TEXTUAL_DRIVER
  if os.environ.get('TEXTUAL_DRIVER'):
    return True
  return sys.stdin.isatty() and sys.stdout.isatty()


class _DebugLogHandler(logging.Handler):
  """Logging handler that appends formatted records to a list."""

  def __init__(self, lines: list[str]) -> None:
    super().__init__()
    self._lines = lines

  def emit(self, record: logging.LogRecord) -> None:
    try:
      self._lines.append(self.format(record))
    except Exception:
      self.handleError(record)


class _DebugScreen(Screen):
  """Modal screen showing the captured debug log. Toggled via Ctrl-O."""

  BINDINGS = [
    Binding('escape', 'app.pop_screen', 'Close'),
    Binding('ctrl+o', 'app.pop_screen', 'Close'),
    Binding('q', 'app.pop_screen', 'Close'),
  ]

  CSS = """
  #debug-title { dock: top; height: 1; padding: 0 1; background: $boost; }
  #debug-output { height: 1fr; border: solid $primary; }
  """

  def __init__(self, lines: list[str]) -> None:
    super().__init__()
    self._lines = lines

  def compose(self) -> ComposeResult:
    yield Static('Debug Output  (Esc / Ctrl-O / q to close)', id='debug-title')
    yield RichLog(id='debug-output', highlight=True, markup=False)
    yield Footer()

  def on_mount(self) -> None:
    log = self.query_one('#debug-output', RichLog)
    if not self._lines:
      log.write('(no debug messages)')
    else:
      for line in self._lines:
        log.write(line)
    log.scroll_end(animate=False)


class TUIApp(mixin_Config, TextualApp):
  """Textual App with per-instance config via self.my().

  Works standalone (``app.run()``) or embedded in a TUILauncher via AppScreen.
  Use ``self.done(result)`` to finish — it calls ``exit()`` or ``dismiss()``
  depending on context.

  Override ``cli()`` to provide a CLI fallback when textual is unavailable.
  Use ``MyApp.main()`` as the unified entry point.

  Built-in bindings (inherited by all subclasses):
    q       — quit (calls done())
    Ctrl-O  — toggle debug log overlay (shows captured logging output)

  Async helper:
    ``with self.loading('#widget-id'): ...`` — overlay Textual's animated
    loading indicator on a widget while a slow operation runs.
  """

  BINDINGS = [
    Binding('q', 'tuiapp_done', 'Quit', show=False),
    Binding('ctrl+o', 'tuiapp_toggle_debug', 'Debug', show=False),
  ]

  _screen_wrapper: Screen | None = None

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._debug_lines: list[str] = []
    self._log_handler = _DebugLogHandler(self._debug_lines)
    self._log_handler.setLevel(logging.DEBUG)
    self._log_handler.setFormatter(
      logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', '%H:%M:%S'),
    )
    logging.getLogger().addHandler(self._log_handler)

  def debug(self, msg: str) -> None:
    """Append a line to the debug buffer (visible via Ctrl-O)."""
    self._debug_lines.append(str(msg))

  def action_tuiapp_done(self) -> None:
    self.done(result=None)

  def action_tuiapp_toggle_debug(self) -> None:
    if isinstance(self.screen, _DebugScreen):
      self.pop_screen()
    else:
      self.push_screen(_DebugScreen(self._debug_lines))

  def loading(self, selector: str | None = None):
    """Context manager — overlay Textual's loading indicator while running.

    Usage::

        with self.loading('#video-table'):
            items = expensive_fetch()
    """
    from contextlib import contextmanager

    @contextmanager
    def _cm():
      try:
        widget = self.query_one(selector) if selector else self.screen
      except Exception:
        widget = None
      if widget is not None:
        widget.loading = True
      try:
        yield
      finally:
        if widget is not None:
          try:
            widget.loading = False
          except Exception:
            pass

    return _cm()

  def done(self, result=None) -> None:
    """Finish this app. Works in both standalone and embedded mode."""
    try:
      logging.getLogger().removeHandler(self._log_handler)
    except Exception:
      pass
    if self._screen_wrapper is not None:
      self._screen_wrapper.dismiss(result=result)
    else:
      self.exit(result=result)

  def cli(self):
    """CLI fallback. Override in subclasses."""
    print(f'{self.__class__.__name__}: no CLI mode defined')
    return None

  @classmethod
  def main(cls, **kwargs):
    """Run this app — TUI if possible, CLI fallback otherwise."""
    instance = cls(**kwargs)
    if _tui_available():
      return instance.run()
    else:
      return instance.cli()


class AppScreen(Screen):
  """Wraps a TUIApp instance as a pushable Screen within a TUILauncher."""

  BINDINGS = [Binding('escape', 'back', 'Back')]

  def __init__(self, wrapped: TUIApp) -> None:
    super().__init__()
    self._wrapped = wrapped
    self._wrapped._screen_wrapper = self

  def compose(self) -> ComposeResult:
    yield from self._wrapped.compose()

  def on_mount(self) -> None:
    if hasattr(self._wrapped, 'on_mount'):
      self._wrapped.on_mount()

  def action_back(self) -> None:
    self.dismiss(result=None)


class LauncherCommands(Provider):
    """Command palette provider for TUILauncher."""

    def _commands(self) -> dict[str, callable]:
        launcher = self.app
        commands = {
            'Show Info': launcher.action_show_info,
            'Edit Config': lambda: launcher._open_config_editor(),
            'Toggle Output': launcher.action_toggle_output,
            'Toggle Dark Mode': launcher.action_toggle_dark,
        }
        if hasattr(launcher, '_running_apps'):
            for name in launcher._running_apps:
                commands[f'Switch to: {name}'] = lambda n=name: launcher.push_screen(launcher._running_apps[n])
        return commands

    async def discover(self) -> Hits:
        for name, callback in self._commands().items():
            yield Hit(1, name, callback)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, callback in self._commands().items():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback)


class TUILauncher(TUIApp):
    """Base TUI superapp launcher.

    Subclass and set ``TITLE`` / ``MENU_TITLE``, then pass to
    :func:`launcher_main`.
    """

    COMMANDS = TextualApp.COMMANDS | {LauncherCommands}

    TITLE = 'Launcher'
    MENU_TITLE = 'Apps'

    CSS = """
    Screen {
        align: center top;
    }
    #process-bar {
        dock: top;
        height: auto;
        max-height: 6;
    }
    .process-row {
        height: 1;
        padding: 0 1;
    }
    .process-row.active-log {
        background: $primary 20%;
    }
    .proc-spinner {
        width: 3;
        height: 1;
        min-width: 3;
    }
    .proc-status {
        height: 1;
        width: 1fr;
    }
    .log-toggle {
        width: auto;
        height: 1;
        min-width: 8;
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
        width: 1fr;
        max-height: 100%;
        margin: 0;
        border: none;
        padding: 1 4;
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
        height: 1;
    }
    ListItem > Static {
        width: 100%;
        height: 1;
        text-wrap: nowrap;
        text-overflow: ellipsis;
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
        Binding('i', 'show_info', 'Info'),
    ]

    def __init__(self, apps: dict[str, dict], app_dir: Path) -> None:
        super().__init__()
        self._apps = apps
        self._app_dir = app_dir
        self._selected_app: dict | None = None
        self._phase = 'apps'  # apps → modes → ask
        self._processes: dict[int, ProcessRow] = {}
        self._proc_counter = 0
        self._active_log: int | None = None
        self._running_apps: dict[str, AppScreen] = {}  # name → screen

    def compose(self) -> ComposeResult:
        yield StatusHeader()
        yield Vertical(id='process-bar')
        yield RichLog(id='output-panel', markup=True)
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
            if not item.enabled:
                self.bell()
                return
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
            if not mode_item.enabled:
                self.bell()
                return
            self._resolve_mode(mode_item.mode_key, mode_item.mode_def)

    def _show_modes(self, app_def: dict, modes: dict) -> None:
        self._phase = 'modes'
        title = self.query_one('#menu-title', Static)
        title.update(f'{app_def.get("name", "")} — Select Mode')
        lv = self.query_one('#app-list', ListView)
        lv.clear()
        for mk, md in modes.items():
            lv.append(ModeItem(mk, md, app_def=app_def))

    def _resolve_mode(self, mode_key: str, mode_def: dict | None) -> None:
        mode_def = mode_def or {}
        base_args = build_args(mode_def)
        ask_for = mode_def.get('ask_for')
        # Check mode-level then app-level for module/class
        tui_module = mode_def.get('module') or self._selected_app.get('module')
        tui_class = mode_def.get('class') or self._selected_app.get('class')
        if ask_for:
            self._show_ask_form(ask_for, base_args, mode_def=mode_def)
        elif tui_module and tui_class:
            self._launch_tui_app({**self._selected_app, 'module': tui_module, 'class': tui_class}, base_args)
        elif mode_def.get('inline'):
            # Run in background with output capture
            self._run_inline(base_args)
        else:
            # Default: suspend TUI, run subprocess with terminal, resume
            self._run_suspended(base_args)

    def _run_suspended(self, cli_args: list[str]) -> None:
        """Exit TUI, run subprocess with full terminal access, then re-enter."""
        self.exit(result={'app': self._selected_app, 'args': cli_args})

    def _launch_tui_app(self, app_def: dict, cli_args: list[str]) -> None:
        """Import a TUIApp class and push it as a screen."""
        import importlib
        module_name = app_def['module']
        class_name = app_def['class']
        app_name = app_def.get('name', class_name)

        # If already running, switch to it
        if app_name in self._running_apps:
            self.push_screen(self._running_apps[app_name])
            return

        # Add app's directory to sys.path for import
        app_cwd = str(resolve_cwd(self._app_dir, app_def))
        if app_cwd not in sys.path:
            sys.path.insert(0, app_cwd)

        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        instance = cls()
        screen = AppScreen(instance)
        self._running_apps[app_name] = screen
        self.install_screen(screen, name=f'app-{app_name}')

        def on_result(result):
            self._running_apps.pop(app_name, None)
            if result is not None:
                _log.info('App %s returned: %s', app_name, result)

        self.push_screen(screen, callback=on_result)
        self._phase = 'apps'

    # ── Inline / background execution ────────────────────────────────────

    def run_task(self, name: str, fn, *args, **kwargs) -> int:
        """Start a background task with spinner and log capture.

        *fn* is called in a worker thread as ``fn(*args, log=log_fn, **kwargs)``.
        The injected ``log`` callback accepts a string and:

        1. Appends it to the task's scrollback (viewable via the process row).
        2. Emits it at ``DEBUG`` level through Python's :mod:`logging`.

        Returns the task ID (usable with :meth:`show_process_logs`).
        """
        self._proc_counter += 1
        proc_id = self._proc_counter

        row = ProcessRow(proc_id, name)
        self._processes[proc_id] = row

        bar = self.query_one('#process-bar')
        bar.mount(row)

        self._run_task_worker(proc_id, name, fn, args, kwargs)
        return proc_id

    @work(thread=True)
    def _run_task_worker(self, proc_id, name, fn, args, kwargs):
        def log_fn(line):
            _log.debug('[%s] %s', name, line)
            self.call_from_thread(self._append_output, proc_id, str(line))

        kwargs['log'] = log_fn
        try:
            fn(*args, **kwargs)
        except Exception as e:
            log_fn(f'Error: {e}')
        self.call_from_thread(self._process_done, proc_id)

    def _run_inline(self, cli_args: list[str]) -> None:
        """Start a background process with its own spinner row."""
        self._proc_counter += 1
        proc_id = self._proc_counter
        app_def = self._selected_app
        app_name = app_def.get('name', '')

        row = ProcessRow(proc_id, app_name)
        self._processes[proc_id] = row

        bar = self.query_one('#process-bar')
        bar.mount(row)

        # Return to apps list so user can keep navigating
        self._phase = 'apps'
        self._selected_app = None
        title = self.query_one('#menu-title', Static)
        title.update(self.MENU_TITLE)
        lv = self.query_one('#app-list', ListView)
        lv.clear()
        for k, v in self._apps.items():
            lv.append(AppItem(k, v))
        self._run_inline_cmd(cli_args, proc_id, app_def)

    @work(thread=True)
    def _run_inline_cmd(
        self, cli_args: list[str], proc_id: int, app_def: dict,
    ) -> None:
        cmd = _resolve_cmd(self._app_dir, app_def)
        if not getattr(sys, 'frozen', False):
            cmd.insert(1, '-u')
        cmd += cli_args
        rc: int | None = None
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                cwd=resolve_cwd(self._app_dir, app_def),
            )
            for line in proc.stdout:
                line = line.rstrip('\n\r')
                if line:
                    self.call_from_thread(self._append_output, proc_id, line)
            proc.wait()
            rc = proc.returncode
        except Exception as e:
            self.call_from_thread(
                self._append_output, proc_id, f'Error: {e}',
            )
        self.call_from_thread(self._process_done, proc_id, rc)

    def _append_output(self, proc_id: int, line: str) -> None:
        """Append a line to a process's log buffer and update its status."""
        row = self._processes.get(proc_id)
        if not row:
            return
        row.log_lines.append(line)
        status = row.query_one('.proc-status', Static)
        display = line if len(line) <= 70 else line[:67] + '…'
        display = display.replace('[', '\\[')
        status.update(f' [dim]{display}[/dim]')
        # Live-append if this process's logs are currently shown
        if self._active_log == proc_id:
            panel = self.query_one('#output-panel', RichLog)
            panel.write(line)

    def _process_done(self, proc_id: int, rc: int | None = None) -> None:
        """Called when a background process finishes."""
        row = self._processes.get(proc_id)
        if not row:
            return
        spinner = row.query_one(SpinnerIndicator)
        spinner.stop()
        status = row.query_one('.proc-status', Static)
        if rc == 0:
            verdict = '[green]done[/green]'
        elif rc is None:
            verdict = '[red]error[/red]'
        else:
            verdict = f'[red]failed (rc={rc})[/red]'
        status.update(
            f' [bold]{row.app_name}[/bold] {verdict}'
            f'  [dim]click for logs[/dim]'
        )

    def show_process_logs(self, proc_id: int) -> None:
        """Show or toggle the log panel for a specific process."""
        panel = self.query_one('#output-panel', RichLog)
        if self._active_log == proc_id and panel.has_class('visible'):
            panel.remove_class('visible')
            self._processes[proc_id].remove_class('active-log')
            self._active_log = None
            return
        # Deselect previous
        if self._active_log is not None and self._active_log in self._processes:
            self._processes[self._active_log].remove_class('active-log')
        # Populate and show
        self._active_log = proc_id
        self._processes[proc_id].add_class('active-log')
        panel.clear()
        for line in self._processes[proc_id].log_lines:
            panel.write(line)
        panel.add_class('visible')

    def action_toggle_output(self) -> None:
        """Toggle the output panel for the current or most recent process."""
        panel = self.query_one('#output-panel', RichLog)
        if panel.has_class('visible'):
            panel.remove_class('visible')
            if self._active_log is not None and self._active_log in self._processes:
                self._processes[self._active_log].remove_class('active-log')
            self._active_log = None
        elif self._processes:
            proc_id = self._active_log or max(self._processes)
            self.show_process_logs(proc_id)

    def action_show_info(self) -> None:
        """Show Env config and app state in a modal screen."""
        import pprint
        sections: list[tuple[str, str]] = [
            ('Env', f'name={Env.name}  initialized={Env.initialized}\n'
                    f'app_path={Env.app_path}'),
        ]
        for key, val in Env.data.items():
            sections.append((key, pprint.pformat(val)))
        if self._my:
            sections.append(('Instance config', pprint.pformat(self._my)))
        self.push_screen(InfoScreen(sections))

    def _open_config_editor(self) -> None:
        """Open the config editor as an AppScreen."""
        from .config_editor import ConfigEditorApp
        name = 'Config Editor'
        if name in self._running_apps:
            self.push_screen(self._running_apps[name])
            return
        editor = ConfigEditorApp(
            root_config=Env.config_file,
            project_root=self._app_dir,
        )
        screen = AppScreen(editor)
        self._running_apps[name] = screen
        self.install_screen(screen, name='app-config-editor')
        self.push_screen(screen, callback=lambda r: self._running_apps.pop(name, None))

    # ── Ask form ─────────────────────────────────────────────────────────

    def _show_ask_form(
        self, fields: list, base_args: list[str] | None = None,
        mode_def: dict | None = None,
    ) -> None:
        self._phase = 'ask'
        self._base_args = base_args or []
        self._ask_mode_def = mode_def or {}
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

        app_def = self._selected_app
        mode_def = self._ask_mode_def

        if mode_def.get('inline'):
            # Clean up ask form, return to app list, run in background
            self._cleanup_ask_form()
            self._run_inline_with_app(app_def, args)
        else:
            # Exit TUI, run subprocess
            self.exit(result={'app': app_def, 'args': args})

    def _cleanup_ask_form(self) -> None:
        """Remove ask form widgets and return to app list."""
        menu = self.query_one('#menu')
        for widget in list(menu.children):
            if widget.id and widget.id.startswith('ask-'):
                widget.remove()
            elif isinstance(widget, (Input, OptionList, Static)) \
                    and widget.id not in ('menu-title', 'app-list'):
                widget.remove()
        lv = self.query_one('#app-list', ListView)
        lv.display = True
        self._phase = 'apps'
        self._selected_app = None
        title = self.query_one('#menu-title', Static)
        title.update(self.MENU_TITLE)
        lv.clear()
        for k, v in self._apps.items():
            lv.append(AppItem(k, v))

    def _run_inline_with_app(self, app_def: dict, cli_args: list[str]) -> None:
        """Run an inline process from a specific app_def (used after ask form)."""
        saved = self._selected_app
        self._selected_app = app_def
        self._run_inline(cli_args)
        self._selected_app = saved

    # ── Navigation ───────────────────────────────────────────────────────

    def action_back(self) -> None:
        if self._phase == 'apps':
            # Hide output panel if visible, otherwise quit
            panel = self.query_one('#output-panel', RichLog)
            if panel.has_class('visible'):
                panel.remove_class('visible')
                if self._active_log is not None and self._active_log in self._processes:
                    self._processes[self._active_log].remove_class('active-log')
                self._active_log = None
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
    app_class: type[TUILauncher],
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
        '--serve', action='store_true',
        help='Serve the TUI as a web app on localhost',
    )
    parser.add_argument(
        '--port', type=int, default=8566,
        help='Port for the web server (default: 8566)',
    )
    parser.add_argument(
        '--host', default='localhost',
        help='Host to bind the web server to (default: localhost)',
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
            suffix = ''
            if not platform_ok(app_def):
                suffix = f'  [{_platform_label(app_def)} only]'
            print(f'  {icon}  {key:12s}  {name} — {desc}{suffix}')
        return

    if args.serve:
        try:
            from textual_serve.server import Server
        except ImportError:
            print('textual-serve is required for --serve.')
            print('Install with:  pip install gppu[serve]')
            sys.exit(1)
        cmd = shlex.join([sys.executable, sys.argv[0]])
        server = Server(cmd, host=args.host, port=args.port, title=description)
        server.serve()
        return

    # Direct launch
    if args.app:
        app_def = apps[args.app]
        if not platform_ok(app_def):
            print(
                f"{args.app!r} is restricted to {_platform_label(app_def)}; "
                f"current OS is {Env.os.name}",
                file=sys.stderr,
            )
            sys.exit(2)
        launch_app(app_dir, app_def, args.extra or None)
        return

    # CLI fallback when no TUI available
    if not _tui_available():
        _launcher_cli(apps, app_dir)
        return

    # TUI launcher — loop back after sub-app exits
    while True:
        tui = app_class(apps, app_dir)
        result = tui.run()
        if not result:
            break
        launch_app(app_dir, result['app'], result.get('args') or None)


def _launcher_cli(apps: dict[str, dict], app_dir: Path) -> None:
    """Simple CLI fallback for launcher when TUI is unavailable."""
    app_keys = list(apps.keys())
    while True:
        print('')
        for i, (key, app_def) in enumerate(apps.items(), 1):
            icon = app_def.get('icon', '')
            name = app_def.get('name', key)
            desc = app_def.get('description', '')
            print(f'  {i}. {icon}  {name} — {desc}')
        print(f'  q. Quit')
        print('')
        choice = input('Select: ').strip()
        if choice.lower() == 'q' or not choice:
            break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(app_keys):
                launch_app(app_dir, apps[app_keys[idx]])
            else:
                print(f'  Invalid choice: {choice}')
        except ValueError:
            if choice in apps:
                launch_app(app_dir, apps[choice])
            else:
                print(f'  Unknown: {choice}')
