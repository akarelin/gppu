"""gppu.tui — Reusable TUI superapp launcher framework and selector widgets."""

from .launcher import (
    AppItem,
    ModeItem,
    SpinnerIndicator,
    LauncherApp,
    build_args,
    resolve_cwd,
    launch_app,
    load_app_registry,
    launcher_main,
)

from .selectors import (
    Selector,
    DetailedSelector,
    DetailScreen,
    ui_select,
    ui_select_rows,
)

__all__ = [
    # Launcher framework
    'AppItem',
    'ModeItem',
    'SpinnerIndicator',
    'LauncherApp',
    'build_args',
    'resolve_cwd',
    'launch_app',
    'load_app_registry',
    'launcher_main',
    # Selector widgets
    'Selector',
    'DetailedSelector',
    'DetailScreen',
    'ui_select',
    'ui_select_rows',
]
