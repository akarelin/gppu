"""gppu.tui — Reusable TUI superapp launcher framework, widgets, and helpers.

Public surface is organized as:

- **Launcher / base classes** (``launcher``) — ``TUIApp``, ``TUILauncher``,
  ``AppScreen``; the sub-app registry + launch plumbing.
- **Selectors** (``selectors``) — list-style pickers with an optional detail
  pane (``ui_select``, ``ui_select_rows``, ``Selector``, ``DetailedSelector``).
- **Config editor** (``config_editor``) — ``ConfigEditorApp`` for editing YAML
  config via TUI.
- **Progress** (``progress``) — streaming per-item indicators
  (``TickProgress`` dim dots, ``MarkerProgress`` classified colored glyphs).
- **Workers** (``workers``) — ``WorkerPool`` + ``WorkerRow`` for rendering
  concurrent task state in a stack with aggregate footer.
- **Debug** (``debug``) — ``DebugSink`` (callable, ring buffer + file),
  ``DebugScreen`` modal, ``DebugMixin`` wiring both + F12 bindings.
- **Icons** (``icons``) — canonical state glyphs + spinner frame sets.
- **Viz** (``viz``) — ``Heatmap`` activity grid (and any future widgets).

If your app needs a reusable pattern and it isn't here, the place to add it
is inside this package — not inside the app.  See
``_/inbox/gppu-tui-sessionmanager.md`` for the scratch on what's planned.
"""

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

from .progress import (
    Vendor,
    TickProgress,
    MarkerProgress,
    marker_rich,
    marker_ansi,
    legend_rich,
    legend_ansi,
)

from .workers import (
    WorkerPool,
    WorkerRow,
    WorkerState,
)

from .debug import (
    DebugLogger,
    DebugSink,
    DebugScreen,
    DebugMixin,
    make_debug_sink,
)

from .icons import (
    Glyph,
    STATE_GLYPHS,
    SPINNERS,
    glyph_rich,
    glyph_ansi,
    spinner_frames,
)

from .viz import Heatmap, render_heatmap_lines

from .modals import ConfirmScreen, InputScreen

from .loaders import LoaderMixin

from .cache import CachedFetcher, PaginatedFetcher, CacheRefreshMixin

from .tree import (
    TreeEntry,
    TreeAdapter,
    FilesystemAdapter,
    GDriveAdapter,
    TreeBrowser,
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
    # Progress
    'Vendor',
    'TickProgress',
    'MarkerProgress',
    'marker_rich',
    'marker_ansi',
    'legend_rich',
    'legend_ansi',
    # Workers
    'WorkerPool',
    'WorkerRow',
    'WorkerState',
    # Debug
    'DebugLogger',
    'DebugSink',
    'DebugScreen',
    'DebugMixin',
    'make_debug_sink',
    # Icons
    'Glyph',
    'STATE_GLYPHS',
    'SPINNERS',
    'glyph_rich',
    'glyph_ansi',
    'spinner_frames',
    # Viz
    'Heatmap',
    'render_heatmap_lines',
    # Modals
    'ConfirmScreen',
    'InputScreen',
    # Loaders
    'LoaderMixin',
    # Cache
    'CachedFetcher',
    'PaginatedFetcher',
    'CacheRefreshMixin',
    # Tree
    'TreeEntry',
    'TreeAdapter',
    'FilesystemAdapter',
    'GDriveAdapter',
    'TreeBrowser',
]
