#!/usr/bin/env python3
"""Index-first folder browser: ``python -m examples.handler_browser``.

Starts in the current directory, like handler_ls. Enter/arrows expand folders;
i creates or refreshes the selected folder's local index (one level). Cached
listings are snapshots: new, changed and removed files appear after refresh.
Browsing an unindexed folder identifies entries; indexing probes its files
through the same handlers used by handler_ls.

Persistence stores JSON metadata in its native _persist.db beside the files.
Only the HandlerBrowser namespace is written. No database is created by browsing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from gppu import Error, format_size
from gppu.data import Persistence
from gppu.tui import TreeEntry, TreeTable, TreeTableColumn, TUIApp
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Static

from examples.handler_ls import ListingHandler

INDEX_FILE = '_persist.db'  # Native gppu.data.Persistence SQLite filename.
INDEX_NAMESPACE = 'HandlerBrowser'
COLUMNS = tuple(TreeTableColumn(key, title) for key, title in (
  ('source', 'Source'), ('handlers', 'Handlers'), ('files', 'Files'),
  ('folders', 'Folders'), ('size', 'Size'), ('span', 'Span'),
))


def load_index(folder: Path) -> dict | None:
  """SQLite operations run together in asyncio.to_thread, including open/close."""
  if (folder / INDEX_FILE).is_file():
    with Persistence(str(folder), backend='sqlite') as index:
      return index.load(INDEX_NAMESPACE, '.')
  return None


def save_index(folder: Path, snapshot: dict) -> None:
  with Persistence(str(folder), backend='sqlite') as index:
    index.upsert(INDEX_NAMESPACE, '.', snapshot)


async def read_folder(folder: Path, *, refresh: bool = False) -> dict:
  """Read persisted metadata first; explicitly refresh through async handlers."""
  if not refresh:
    snapshot = await asyncio.to_thread(load_index, folder)
    if snapshot is not None:
      return snapshot
  handler = ListingHandler(strict=True)
  root, = await handler.identify(folder, recursive=False)
  if not root.is_folder or 'ignored' in root.handlers:
    raise ValueError(f'{folder}: not a browsable folder')
  records = [record async for record in handler.walk(root, recursive=False) if record.name != INDEX_FILE]
  if refresh:
    records = [
      record if record.is_folder else (await handler.probe(record.path, recursive=False))[0]
      for record in records
    ]
  # Only display metadata is persisted; typed objects and source text stay out.
  rows = [dict(record.metadata, name=record.name, path=record.name) for record in records]
  spans = [record.span for record in records if record.span is not None]
  root_meta = dict(root.metadata, name=root.name, path='.',
    files=sum(not record.is_folder for record in records),
    folders=sum(record.is_folder for record in records),
    size=sum(record.size for record in records),
    span=(min(span[0] for span in spans), max(span[1] for span in spans)) if spans else None,
  )
  snapshot = json.loads(json.dumps(
    {'root': root_meta, 'children': rows, 'source': 'Index' if refresh else 'Filesystem'},
    default=str,
  ))
  if refresh:
    await asyncio.to_thread(save_index, folder, snapshot)
  return snapshot


def entry(path: Path, metadata: dict, source: str) -> TreeEntry:
  """Project handler metadata onto the shared tree table."""
  span = metadata.get('span')
  return TreeEntry(str(path), path.name or str(path),
    is_container=metadata['type'] == 'folder' and 'ignored' not in metadata['handlers'],
    meta={
      **metadata, 'source': source, 'handlers': ', '.join(metadata['handlers']),
      'size': format_size(metadata['size']) if metadata['size'] else '',
      'span': ' – '.join(moment[:10] for moment in span) if span else '',
    },
  )


class HandlerBrowser(TUIApp):
  """A TreeTable adapter plus background calls to read_folder."""

  TITLE = 'Handlers · local indexes'
  CSS = '#status { height: 2; }'
  BINDINGS = [
    Binding('i', 'index', 'Create / refresh index'),
    Binding('backspace', 'parent', 'Parent'),
    Binding('q', 'tuiapp_done', 'Quit'),
  ]

  def __init__(self, root: Path) -> None:
    super().__init__()
    self.folder = root
    self.rows: dict[str, list[TreeEntry]] = {}
    self.pending: set[str] = set()

  def root(self) -> TreeEntry:
    return TreeEntry(str(self.folder), self.folder.name or str(self.folder), is_container=True)

  def children(self, node: TreeEntry) -> list[TreeEntry]:
    if node.id not in self.rows:
      self.fetch(Path(node.id))
    return self.rows.get(node.id, [])

  def compose(self) -> ComposeResult:
    yield TreeTable(self, columns=COLUMNS, id='files')
    yield Static('Expand a folder to browse; i indexes one folder. Source shows where metadata came from.', id='status', markup=False)
    yield Footer()

  def on_mount(self) -> None:
    self.query_one(DataTable).focus()

  @work
  async def fetch(self, folder: Path, *, refresh: bool = False) -> None:
    key = str(folder)
    if key in self.pending:
      return
    self.pending.add(key)

    status = self.query_one('#status', Static)
    status.update(f'{"Indexing" if refresh else "Loading"} {folder}')
    try:
      snapshot = await read_folder(folder, refresh=refresh)
      source = snapshot['source']
      self.rows[key] = [entry(folder / row['name'], row, source) for row in snapshot['children']]
      self.query_one(TreeTable).refresh_entry(key, entry=entry(folder, snapshot['root'], source))
      status.update(f'{folder} · {source} · one level')
    except Exception as error:
      Error(f'{folder}: {error}')
      status.update(f'Error: {folder}: {error}')
    finally:
      self.pending.discard(key)

  def action_index(self) -> None:
    node = self.query_one(TreeTable).selected_entry
    if node is not None:
      folder = Path(node.id)
      if node.meta.get('type') == 'file':
        folder = folder.parent
      self.fetch(folder, refresh=True)

  def action_parent(self) -> None:
    self.folder = self.folder.parent
    self.query_one(TreeTable).reset()


if __name__ == '__main__':
  HandlerBrowser(Path.cwd()).run()
