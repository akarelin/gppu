#!/usr/bin/env python3
"""Browse Locations, folders, archives and files as one tree, using only gppufs.ls and gppufs.info."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from gppu import Env, Error, format_size
from gppu.handlers import GppuCatalog, GppuFileSystem
from gppu.tui import TreeEntry, TreeTable, TreeTableColumn, TUIApp
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Static, TextArea

ROOT = ''  # the tree root stands for gppufs.ls(None) and gppufs.info(None)
LOADING = '\x00loading'
FAILED = '\x00failed'
COLUMNS = (TreeTableColumn('handlers', 'Handlers', 24), TreeTableColumn('files', 'Files', 9),
  TreeTableColumn('folders', 'Folders', 9), TreeTableColumn('bytes', 'Bytes', 12), TreeTableColumn('span', 'Span', 25))


class Listing:
  """gppufs as a tree: children come from ls, asked for once and awaited; Locations the catalog names stay in the tree."""

  def __init__(self, request: Callable[[TreeEntry], None]) -> None:
    self._request = request
    self._children: dict[str, list[TreeEntry]] = {}
    self._pending: set[str] = set()
    self._locations: dict[str, list[TreeEntry]] = {}  # parent address -> Locations the catalog places beneath it
    self.location_addresses: set[str] = set()

  def root(self) -> TreeEntry:
    return TreeEntry(id=ROOT, label=Text('…'), is_container=True)

  def children(self, entry: TreeEntry) -> list[TreeEntry]:
    loaded = self._children.get(entry.id)
    if loaded is not None:
      return loaded
    if entry.id not in self._pending:
      self._pending.add(entry.id)
      self._request(entry)
    return [*self._locations.get(entry.id, ()), TreeEntry(entry.id + LOADING, Text('loading…', style='dim'), meta={'placeholder': True})]

  def entry(self, row: dict, entry_id: str | None = None) -> TreeEntry:
    """One gppufs row as a tree row: a Location in bold, unknown totals blank."""
    meta = row['gppu']
    blank = lambda value, show=str: '' if value is None else show(value)
    label = Text(meta['name'], style='bold' if row['name'] in self.location_addresses else '')
    return TreeEntry(row['name'] if entry_id is None else entry_id, label, meta['is_container'], {
      'handlers': ', '.join(meta['handlers']), 'files': blank(meta['files']), 'folders': blank(meta['folders']),
      'bytes': blank(meta['bytes'], format_size),
      'span': ' – '.join(moment[:10] for moment in meta['span']) if meta['span'] else ''})

  def store(self, entry_id: str, current: dict, rows: list[dict]) -> TreeEntry:
    """Keep a listing and return the listed entry itself.

    A catalog root lists every Location with its parent; each goes under its
    parent Location, so the Locations tree shows before any folder is read.
    """
    self._pending.discard(entry_id)
    if entry_id == ROOT and any('location' in row['gppu'] for row in rows):
      self.location_addresses = {row['name'] for row in rows}
      self._locations = {}
      for row in rows:
        parent = ROOT if row['gppu']['parent'] == current['name'] else row['gppu']['parent']
        self._locations.setdefault(parent, []).append(self.entry(row))
      rows = [row for row in rows if row['gppu']['parent'] == current['name']]
    listed = [self.entry(row) for row in rows]
    shown = {item.id for item in listed}
    listed.extend(item for item in self._locations.get(entry_id, ()) if item.id not in shown)
    self._children[entry_id] = listed
    return self.entry(current, entry_id)

  def failed(self, entry_id: str, error: Exception) -> bool:
    """A listing that could not be read keeps what was shown before, or says why nothing is; True when that row is new."""
    self._pending.discard(entry_id)
    if entry_id in self._children:
      return False
    self._children[entry_id] = [TreeEntry(entry_id + FAILED, Text(f'error: {error}', style='red'), meta={'placeholder': True})]
    return True


class HandlerBrowser(TUIApp):
  TITLE = 'gppufs'
  CSS = '#tree { height: 2fr; } #metadata { height: 1fr; } #status { height: auto; }'
  BINDINGS = [
    Binding('r', 'refresh_source', 'Refresh from source'),
    Binding('q', 'tuiapp_done', 'Quit'),
  ]

  def __init__(self, gppufs: GppuCatalog | GppuFileSystem) -> None:
    super().__init__()
    self.gppufs = gppufs
    self.listing = Listing(self.load)
    self.current: dict | None = None

  def compose(self) -> ComposeResult:
    yield Static('Loading…', id='status', markup=False)
    yield TreeTable(self.listing, columns=COLUMNS, id='tree')
    yield TextArea(read_only=True, id='metadata')
    yield Footer()

  def on_mount(self) -> None:
    self.query_one(TreeTable).query_one(DataTable).focus()

  @staticmethod
  def address(entry: TreeEntry) -> str | None:
    return None if entry.id == ROOT else entry.id

  @work(exclusive=False, group='listing')
  async def load(self, entry: TreeEntry, *, refresh: bool = False) -> None:
    status = self.query_one('#status', Static)
    status.update(f'Loading {self.address(entry) or "catalog"}…')
    tree = self.query_one(TreeTable)
    try:
      address = self.address(entry)
      if entry.is_container:
        rows = await self.gppufs.ls(address, refresh=refresh)
        current = await self.gppufs.info(address)
        updated = self.listing.store(entry.id, current, rows)
      else:
        current = await self.gppufs.info(address, refresh=refresh)
        updated = self.listing.entry(current)
      tree.refresh_entry(entry.id, entry=updated, reload_children=entry.is_container)
      if tree.selected_entry is not None and tree.selected_entry.id == entry.id:
        self.show_metadata(current)
      status.update(current['name'])
    except Exception as error:
      Error(error)
      if self.listing.failed(entry.id, error):
        tree.refresh_entry(entry.id, reload_children=True)
      status.update(f'Error: {error}')

  def show_metadata(self, metadata: dict) -> None:
    self.current = metadata
    self.query_one(TextArea).load_text(json.dumps({'gppu': metadata['gppu'], **metadata}, indent=2, ensure_ascii=False))

  @work(exclusive=True, group='info')
  async def show_info(self, entry: TreeEntry) -> None:
    try:
      self.show_metadata(await self.gppufs.info(self.address(entry)))
      self.query_one('#status', Static).update(self.current['name'])
    except Exception as error:
      Error(error)
      self.query_one('#status', Static).update(f'Error: {error}')

  def on_tree_table_entry_highlighted(self, event: TreeTable.EntryHighlighted) -> None:
    if not event.entry.meta.get('placeholder'):
      self.show_info(event.entry)

  def action_refresh_source(self) -> None:
    entry = self.query_one(TreeTable).selected_entry
    if entry is None or entry.meta.get('placeholder'):
      return
    self.load(entry, refresh=True)


def main() -> None:
  Env.from_env(name='handlers', app_path=Path(__file__).parent)
  HandlerBrowser(GppuCatalog(Env.glob('catalog'))).run()


if __name__ == '__main__':
  main()
