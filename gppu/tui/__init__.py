"""gppu.tui — Reusable TUI superapp launcher framework and selector widgets."""

from .launcher import (
    _tui_available,
    TUIApp,
    TUILauncher,
    AppScreen,
    AppItem,
    InfoScreen,
    ModeItem,
    ProcessRow,
    SpinnerIndicator,
    StatusHeader,
    build_args,
    resolve_cwd,
    launch_app,
    load_app_registry,
    launcher_main,
)

from .config_editor import ConfigEditorApp

from .selectors import (
    Selector,
    DetailedSelector,
    DetailScreen,
    ui_select,
    ui_select_rows,
)

__all__ = [
    # Base TUI classes
    'TUIApp',
    'TUILauncher',
    'AppScreen',
    # Launcher framework
    'AppItem',
    'InfoScreen',
    'ModeItem',
    'ProcessRow',
    'SpinnerIndicator',
    'StatusHeader',
    'build_args',
    'resolve_cwd',
    'launch_app',
    'load_app_registry',
    'launcher_main',
    # Config editor
    'ConfigEditorApp',
    # Selector widgets
    'Selector',
    'DetailedSelector',
    'DetailScreen',
    'ui_select',
    'ui_select_rows',
]
