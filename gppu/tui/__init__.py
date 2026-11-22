"""gppu.tui — the TUI launcher, its base app and the widgets programs build on.

What programs import from it:

- **Launcher / base classes** (``launcher``) — ``TUIApp``, ``TUILauncher``, ``StatusHeader``; the sub-app registry and
  launch plumbing (``load_app_registry``, ``launch_app``, ``launcher_main``).
- **Selectors** (``selectors``) — ``ui_select`` and ``ui_select_rows``.
- **Progress, workers, modals, loaders** — ``TickProgress``, ``WorkerPool``, ``ConfirmScreen``, ``LoaderMixin``.
- **Tree** (``tree``, ``tree_table``) and ``TaskMatrix``.

The rest of the package is the launcher's own parts (the config editor it opens, the icons its widgets draw) and
widgets no program uses, each in its module.
"""

from .launcher import (
    _tui_available,
    TUIApp,
    TUILauncher,
    StatusHeader,
    launch_app,
    load_app_registry,
    launcher_main,
)

from .selectors import ui_select, ui_select_rows

from .progress import TickProgress

from .workers import WorkerPool

from .modals import ConfirmScreen

from .loaders import LoaderMixin

from .tree import TreeEntry

from .tree_table import TreeTable, TreeTableColumn

from .task_matrix import TaskMatrix


# .. what programs import from gppu.tui, and nothing else: a name no program uses stays in its module, unexported
__all__ = [
    # .. Base TUI classes and the launcher
    'TUIApp',
    'TUILauncher',
    'StatusHeader',
    'launch_app',
    'load_app_registry',
    'launcher_main',
    # .. Selector widgets
    'ui_select',
    'ui_select_rows',
    # .. Progress
    'TickProgress',
    # .. Workers
    'WorkerPool',
    # .. Modals
    'ConfirmScreen',
    # .. Loaders
    'LoaderMixin',
    # .. Tree
    'TreeEntry',
    'TreeTable',
    'TreeTableColumn',
    'TaskMatrix',
]
