<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/task_matrix.py 6d880d83ee7076b2affc37d65de9c9b7dcf5d603 -->
`gppu.tui.task_matrix` provides a selectable grid of hosts and tasks for a Textual app. The user picks which tasks run on which hosts, and the same grid then shows each chosen run as it progresses.

The module's one class is `TaskMatrix`, a widget built on a `DataTable`. Its constructor takes the hosts, the tasks, and the applicable (host, task) cells. Any other cell shows a dash and cannot be selected. Applicable cells start selected unless the caller passes its own `selected` set. With `transposed=True`, tasks become rows and hosts become columns.

Each applicable cell has one state: `pending`, `running`, `ok` or `fail`. Only pending cells can be toggled. `mark` sets a cell's state and redraws it, and `mark_host` sets a status glyph in a host's label without changing the selection. `selected` returns the chosen cells in host-major order. When `locked` is true, no selection change is accepted.

Selection changes go through `toggle` for one cell, `toggle_host` and `toggle_task` for a whole row or column, and `select` to set an exact selection, as a preset does. `toggle_cursor` handles the Space and Enter keys. In the first column it toggles the whole row, and in transposed mode a click on a host's header toggles that host.

`HOST_COLUMN` is the key of the first column, and `STATES` lists the state strings that `mark` accepts. The constructor raises `ValueError` for a cell outside hosts × tasks. `mark` raises `KeyError` for a non-applicable cell and `ValueError` for an unknown state. Call `mark` and `mark_host` only after the widget is mounted, because the table's columns are created in `on_mount`.

## Usage

A program places the matrix in its layout, then updates cell states while it runs:

```python
from textual.app import App
from gppu.tui import TaskMatrix


class Deploy(App):
    def compose(self):
        yield TaskMatrix(
            hosts=['host-a', 'host-b'],
            tasks=['pull', 'restart'],
            applicable=[('host-a', 'pull'), ('host-a', 'restart'), ('host-b', 'pull')],
        )

    def run_cell(self, host, task):
        matrix = self.query_one(TaskMatrix)
        matrix.mark(host, task, 'running')
        matrix.mark(host, task, 'ok')
```
