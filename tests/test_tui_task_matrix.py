from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from gppu.tui import TaskMatrix


class MatrixApp(App):
  def compose(self) -> ComposeResult:
    yield TaskMatrix(
      ('alex-pc', 'trix'),
      ('LLM logs', 'Windows logs'),
      {
        ('alex-pc', 'LLM logs'),
        ('alex-pc', 'Windows logs'),
        ('trix', 'LLM logs'),
      },
      id='tasks',
    )


@pytest.mark.asyncio
async def test_task_matrix_selects_toggles_and_marks_cells() -> None:
  app = MatrixApp()
  async with app.run_test() as pilot:
    matrix = app.query_one(TaskMatrix)
    table = matrix.query_one(DataTable)

    assert matrix.selected == (
      ('alex-pc', 'LLM logs'),
      ('alex-pc', 'Windows logs'),
      ('trix', 'LLM logs'),
    )
    assert table.get_cell('trix', 'Windows logs') == '—'

    table.focus()
    await pilot.press('space')
    assert matrix.selected == (('trix', 'LLM logs'),)
    assert table.get_cell('alex-pc', '__host__') == '☐ alex-pc'

    await pilot.press('right', 'enter')
    assert table.get_cell('alex-pc', '__host__') == '◪ alex-pc'

    matrix.mark('alex-pc', 'LLM logs', 'running')
    assert table.get_cell('alex-pc', 'LLM logs') == '…'
    matrix.mark('alex-pc', 'LLM logs', 'ok')
    assert table.get_cell('alex-pc', 'LLM logs') == '✓'
    matrix.mark('trix', 'LLM logs', 'fail')
    assert table.get_cell('trix', 'LLM logs') == '✗'
    await pilot.pause()
