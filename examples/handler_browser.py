#!/usr/bin/env python3
"""Browse handler metadata using only gppufs.ls and gppufs.info."""

from __future__ import annotations

import asyncio
import json

from gppu import Error, format_size
from gppu.handlers import GppuFileSystem
from gppu.tui import TUIApp
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Static, TextArea

from examples.handler_ls import filesystem


class HandlerBrowser(TUIApp):
  TITLE = 'gppufs · handler metadata'
  CSS = '#files { height: 1fr; } #metadata { height: 1fr; } #status { height: auto; }'
  BINDINGS = [
    Binding('r', 'refresh_source', 'Refresh from source'),
    Binding('backspace', 'parent', 'Parent'),
    Binding('q', 'tuiapp_done', 'Quit'),
  ]

  def __init__(self, gppufs: GppuFileSystem) -> None:
    super().__init__()
    self.gppufs = gppufs
    self.current: dict | None = None
    self.rows: dict[str, dict] = {}

  def compose(self) -> ComposeResult:
    yield Static('Loading…', id='status', markup=False)
    yield DataTable(id='files', cursor_type='row')
    yield TextArea(read_only=True, id='metadata')
    yield Footer()

  def on_mount(self) -> None:
    table = self.query_one(DataTable)
    table.add_columns('Name', 'Type', 'Handlers', 'Files', 'Folders', 'Bytes', 'Span')
    table.focus()
    self.load()

  @work(exclusive=True, group='listing')
  async def load(self, path: str | None = None, *, refresh: bool = False) -> None:
    status = self.query_one('#status', Static)
    status.update(f'Loading {path or "location"}…')
    try:
      rows = await asyncio.to_thread(self.gppufs.ls, path, refresh=refresh)
      current = await asyncio.to_thread(self.gppufs.info, path)
      self.current = current
      self.rows = {row['name']: row for row in rows}
      table = self.query_one(DataTable)
      table.clear()
      for row in rows:
        meta = row['gppu']
        span = ' – '.join(meta['span']) if meta['span'] else ''
        table.add_row(meta['name'], row['type'], ', '.join(meta['handlers']),
          str(meta['files']), str(meta['folders']), format_size(meta['bytes']), span, key=row['name'])
      self.show_metadata(current)
      status.update(current['name'])
    except Exception as error:
      Error(error)
      status.update(f'Error: {error}')

  def show_metadata(self, metadata: dict) -> None:
    self.query_one(TextArea).load_text(json.dumps(metadata, indent=2, ensure_ascii=False))

  @work(exclusive=True, group='info')
  async def show_info(self, path: str) -> None:
    try:
      self.show_metadata(await asyncio.to_thread(self.gppufs.info, path))
    except Exception as error:
      Error(error)
      self.query_one('#status', Static).update(f'Error: {error}')

  def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
    self.show_info(str(event.row_key.value))

  def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
    row = self.rows[str(event.row_key.value)]
    if row['gppu']['is_container']:
      self.load(row['name'])

  def action_parent(self) -> None:
    if self.current is not None and self.current['gppu']['parent'] is not None:
      self.load(self.current['gppu']['parent'])

  def action_refresh_source(self) -> None:
    self.load(None if self.current is None else self.current['name'], refresh=True)


def main() -> None:
  HandlerBrowser(filesystem()).run()


if __name__ == '__main__':
  main()
