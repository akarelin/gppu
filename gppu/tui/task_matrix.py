"""Selectable host-by-task matrix with per-cell execution state."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable
from .icons import glyph_rich


HOST_COLUMN = '__host__'
STATES = frozenset({'pending', 'running', 'ok', 'fail'})


class TaskMatrix(Widget):
  """A host-by-task selector whose cells become progress indicators.

  Applicable cells start selected unless the caller says which ones do; the
  application's configuration is where that belongs. Space or Enter toggles the
  current task cell; using either key in the first column toggles that whole row.

  ``transposed`` puts tasks in rows and hosts in columns, for more tasks than fit
  across; a host's status and selection mark then sit in its column header, and
  clicking the header toggles the host.
  """

  DEFAULT_CSS = """
  TaskMatrix {
    height: 1fr;
  }
  TaskMatrix > DataTable {
    height: 1fr;
  }
  """

  BINDINGS = [Binding('space', 'toggle_cursor', 'Toggle', show=False)]

  def __init__(
    self,
    hosts: Sequence[str],
    tasks: Sequence[str],
    applicable: Iterable[tuple[str, str]],
    *,
    selected: Iterable[tuple[str, str]] | None = None,
    id: str | None = None,
    transposed: bool = False,
  ) -> None:
    super().__init__(id=id)
    self.hosts = tuple(hosts)
    self.tasks = tuple(tasks)
    self.applicable = frozenset(applicable)
    unknown = self.applicable - {
      (host, task) for host in self.hosts for task in self.tasks
    }
    if unknown:
      raise ValueError(f'unknown host/task cells: {sorted(unknown)}')
    self._selected = set(self.applicable if selected is None else selected) & self.applicable
    self._states = {cell: 'pending' for cell in self.applicable}
    self._host_status = {}
    self.locked = False
    self.transposed = transposed

  def compose(self) -> ComposeResult:
    yield DataTable(cursor_type='cell', zebra_stripes=True)

  def on_mount(self) -> None:
    table = self.query_one(DataTable)
    if self.transposed:
      table.add_column('Step', key=HOST_COLUMN, width=max(map(len, self.tasks), default=0) + 2)
      for host in self.hosts:
        table.add_column(self._host_label(host), key=host, width=len(host) + 2)
      for task in self.tasks:
        table.add_row(self._row_cell(task), *(self._task_cell(host, task) for host in self.hosts), key=task)
      return
    # Status glyph, selection mark and name: the status arrives later, so the width is set, not measured.
    table.add_column('Host', key=HOST_COLUMN, width=max(map(len, self.hosts), default=0) + 4)
    for task in self.tasks:
      table.add_column(task, key=task)
    for host in self.hosts:
      table.add_row(
        self._host_cell(host),
        *(self._task_cell(host, task) for task in self.tasks),
        key=host,
      )

  def _update(self, host: str, task: str) -> None:
    row, column = (task, host) if self.transposed else (host, task)
    self.query_one(DataTable).update_cell(row, column, self._task_cell(host, task))

  @property
  def selected(self) -> tuple[tuple[str, str], ...]:
    """Selected cells in stable host-major order."""
    return tuple(
      (host, task)
      for host in self.hosts
      for task in self.tasks
      if (host, task) in self._selected
    )

  def mark(self, host: str, task: str, state: str) -> None:
    """Set and render one applicable cell's execution state."""
    cell = (host, task)
    if cell not in self.applicable:
      raise KeyError(cell)
    if state not in STATES:
      raise ValueError(f'unsupported task state: {state}')
    self._states[cell] = state
    self._update(host, task)

  def toggle_cursor(self) -> None:
    """Toggle the selected cell, or the whole row from the host column."""
    if self.locked:
      return
    table = self.query_one(DataTable)
    key = table.coordinate_to_cell_key(table.cursor_coordinate)
    row, column = str(key.row_key.value), str(key.column_key.value)
    if column == HOST_COLUMN:
      self.toggle_task(row) if self.transposed else self.toggle_host(row)
    else:
      self.toggle(*((column, row) if self.transposed else (row, column)))

  def action_toggle_cursor(self) -> None:
    self.toggle_cursor()

  def mark_host(self, host: str, state: str) -> None:
    """Update an asynchronously loaded host status without changing selection."""
    if host not in self.hosts:
      raise KeyError(host)
    self._host_status[host] = glyph_rich(state)
    self._refresh_host(host)

  def toggle_host(self, host: str) -> None:
    """Select or clear every applicable pending task in one host row."""
    if self.locked:
      return
    cells = tuple(
      (host, task)
      for task in self.tasks
      if (host, task) in self.applicable and self._states[(host, task)] == 'pending'
    )
    self._flip(cells)

  def toggle_task(self, task: str) -> None:
    """Select or clear one task on every applicable pending host."""
    if self.locked:
      return
    self._flip(tuple(
      (host, task)
      for host in self.hosts
      if (host, task) in self.applicable and self._states[(host, task)] == 'pending'
    ))

  def select(self, cells: Iterable[tuple[str, str]]) -> None:
    """Make exactly these applicable pending cells the selection, as a preset does."""
    if self.locked:
      return
    wanted = set(cells) & self.applicable
    for cell in self.applicable:
      if self._states[cell] == 'pending' and (cell in wanted) != (cell in self._selected):
        self._selected.symmetric_difference_update({cell})
        self._update(*cell)
    for host in self.hosts:
      self._refresh_host(host)
    for task in self.tasks:
      self._refresh_task(task)

  def _flip(self, cells: tuple) -> None:
    select = any(cell not in self._selected for cell in cells)
    for cell in cells:
      if select:
        self._selected.add(cell)
      else:
        self._selected.discard(cell)
      self._update(*cell)
    for host in dict.fromkeys(host for host, _ in cells):
      self._refresh_host(host)
    for task in dict.fromkeys(task for _, task in cells):
      self._refresh_task(task)

  def toggle(self, host: str, task: str) -> None:
    """Toggle one applicable pending task cell."""
    if self.locked:
      return
    cell = (host, task)
    if cell not in self.applicable or self._states[cell] != 'pending':
      return
    if cell in self._selected:
      self._selected.remove(cell)
    else:
      self._selected.add(cell)
    self._update(host, task)
    self._refresh_host(host)
    self._refresh_task(task)

  def _refresh_host(self, host: str) -> None:
    table = self.query_one(DataTable)
    if not self.transposed:
      table.update_cell(host, HOST_COLUMN, self._host_cell(host))
      return
    table.columns[host].label = Text.from_markup(self._host_label(host))
    table.refresh()

  def _refresh_task(self, task: str) -> None:
    if self.transposed:
      self.query_one(DataTable).update_cell(task, HOST_COLUMN, self._row_cell(task))

  def _host_label(self, host: str) -> str:
    """A column header: the host's status, then its name. Its selection shows in its cells."""
    return f"{self._host_status.get(host, ' ')} {host}"

  def _row_cell(self, task: str) -> str:
    cells = tuple((host, task) for host in self.hosts if (host, task) in self.applicable)
    selected = sum(cell in self._selected for cell in cells)
    return f"{'☐' if selected == 0 else '☑' if selected == len(cells) else '◪'} {task}"

  def _host_cell(self, host: str) -> str:
    cells = tuple((host, task) for task in self.tasks if (host, task) in self.applicable)
    selected = sum(cell in self._selected for cell in cells)
    mark = '☐' if selected == 0 else '☑' if selected == len(cells) else '◪'
    status = f'{self._host_status[host]} ' if host in self._host_status else ''
    return f'{status}{mark} {host}'

  def _task_cell(self, host: str, task: str) -> str:
    cell = (host, task)
    if cell not in self.applicable:
      return '—'
    state = self._states[cell]
    if state == 'running':
      return '…'
    if state == 'ok':
      return '✓'
    if state == 'fail':
      return '✗'
    return '☑' if cell in self._selected else '☐'

  def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
    event.stop()
    self.toggle_cursor()

  def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
    event.stop()
    if self.transposed and event.column_key.value != HOST_COLUMN:
      self.toggle_host(str(event.column_key.value))
