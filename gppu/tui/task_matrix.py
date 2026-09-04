"""Selectable host-by-task matrix with per-cell execution state."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from textual import events
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable


HOST_COLUMN = '__host__'
STATES = frozenset({'pending', 'running', 'ok', 'fail'})


class TaskMatrix(Widget):
  """A host-by-task selector whose cells become progress indicators.

  Every applicable cell starts selected. Space or Enter toggles the current
  task cell; using either key in the host column toggles that whole row.
  """

  DEFAULT_CSS = """
  TaskMatrix {
    height: 1fr;
  }
  TaskMatrix > DataTable {
    height: 1fr;
  }
  """

  def __init__(
    self,
    hosts: Sequence[str],
    tasks: Sequence[str],
    applicable: Iterable[tuple[str, str]],
    *,
    id: str | None = None,
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
    self._selected = set(self.applicable)
    self._states = {cell: 'pending' for cell in self.applicable}
    self.locked = False

  def compose(self) -> ComposeResult:
    yield DataTable(cursor_type='cell', zebra_stripes=True)

  def on_mount(self) -> None:
    table = self.query_one(DataTable)
    table.add_column('Host', key=HOST_COLUMN)
    for task in self.tasks:
      table.add_column(task, key=task)
    for host in self.hosts:
      table.add_row(
        self._host_cell(host),
        *(self._task_cell(host, task) for task in self.tasks),
        key=host,
      )

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
    self.query_one(DataTable).update_cell(host, task, self._task_cell(host, task))

  def toggle_cursor(self) -> None:
    """Toggle the selected cell, or the whole row from the host column."""
    if self.locked:
      return
    table = self.query_one(DataTable)
    key = table.coordinate_to_cell_key(table.cursor_coordinate)
    host = str(key.row_key.value)
    task = str(key.column_key.value)
    if task == HOST_COLUMN:
      self.toggle_host(host)
    else:
      self.toggle(host, task)

  def toggle_host(self, host: str) -> None:
    """Select or clear every applicable pending task in one host row."""
    cells = tuple(
      (host, task)
      for task in self.tasks
      if (host, task) in self.applicable and self._states[(host, task)] == 'pending'
    )
    select = any(cell not in self._selected for cell in cells)
    for cell in cells:
      if select:
        self._selected.add(cell)
      else:
        self._selected.discard(cell)
    self._refresh_host(host)

  def toggle(self, host: str, task: str) -> None:
    """Toggle one applicable pending task cell."""
    cell = (host, task)
    if cell not in self.applicable or self._states[cell] != 'pending':
      return
    if cell in self._selected:
      self._selected.remove(cell)
    else:
      self._selected.add(cell)
    table = self.query_one(DataTable)
    table.update_cell(host, task, self._task_cell(host, task))
    self._refresh_host(host)

  def _refresh_host(self, host: str) -> None:
    self.query_one(DataTable).update_cell(host, HOST_COLUMN, self._host_cell(host))

  def _host_cell(self, host: str) -> str:
    cells = tuple((host, task) for task in self.tasks if (host, task) in self.applicable)
    selected = sum(cell in self._selected for cell in cells)
    mark = '☐' if selected == 0 else '☑' if selected == len(cells) else '◪'
    return f'{mark} {host}'

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

  async def on_key(self, event: events.Key) -> None:
    if event.key in ('space', 'enter'):
      self.toggle_cursor()
      event.stop()

  def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
    self.toggle_cursor()
