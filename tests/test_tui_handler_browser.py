from __future__ import annotations

import asyncio
import json
import zipfile

import yaml
from textual.widgets import DataTable, Static, TextArea

from examples.handler_browser import HandlerBrowser
from gppu.handlers import GppuCatalog, GppuFileSystem
from gppu.tui import TreeTable


async def settled(app, pilot):
  await app.workers.wait_for_complete()
  await pilot.pause()
  await app.workers.wait_for_complete()
  await pilot.pause()


def labels(app) -> list[str]:
  table = app.query_one(TreeTable).query_one(DataTable)
  return [str(table.get_row_at(index)[0]).strip().lstrip('▶▼ ') for index in range(table.row_count)]


def cell(app, name: str, column: str) -> str:
  tree = app.query_one(TreeTable)
  node = next(node for node in tree._tree_nodes.values() if str(node.entry.label) == name)
  return node.entry.meta[column]


async def select(app, pilot, name: str) -> None:
  tree = app.query_one(TreeTable)
  tree.select(next(entry_id for entry_id, node in tree._tree_nodes.items() if str(node.entry.label) == name))
  await settled(app, pilot)


def test_tui_tree_expands_folders_and_archives_shows_metadata_and_refreshes(tmp_path, monkeypatch):
  async def exercise():
    child = tmp_path / 'child'
    child.mkdir()
    (child / 'note.md').write_text('---\ntitle: Metadata in the TUI\n---\nText')
    with zipfile.ZipFile(tmp_path / 'bundle.zip', 'w') as archive:
      archive.writestr('inside.txt', 'inside')
    (tmp_path / '.git').mkdir()
    fs = GppuFileSystem(tmp_path)
    app = HandlerBrowser(fs)
    async with app.run_test(size=(130, 40)) as pilot:
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'bundle.zip']
      assert app.current['name'] == (await fs.info())['name']
      await select(app, pilot, 'child')
      await pilot.press('right')
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'note.md', 'bundle.zip']
      await pilot.press('f')
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'bundle.zip']
      assert app.query_one(TreeTable).selected_entry.label.plain == 'child'
      await pilot.press('i')
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, 'child', 'bundle.zip']
      await pilot.press('f')
      await pilot.press('i')
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'note.md', 'bundle.zip']
      await select(app, pilot, 'note.md')
      detail = json.loads(app.query_one(TextArea).text)
      assert detail['gppu']['markdown']['title'] == 'Metadata in the TUI'
      (child / 'added.txt').write_text('added')
      await select(app, pilot, 'child')
      await pilot.press('r')
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'added.txt', 'note.md', 'bundle.zip']
      assert cell(app, 'child', 'indexed') == app.current['gppu']['probed_at'][:16]
      await select(app, pilot, tmp_path.name)
      await pilot.press('r')
      await settled(app, pilot)
      assert app.current['gppu']['files'] == 3
      assert app.current['gppu']['bytes'] == sum(
        path.stat().st_size for path in (child / 'note.md', child / 'added.txt', tmp_path / 'bundle.zip'))
      assert labels(app) == [tmp_path.name, '.git', 'child', 'added.txt', 'note.md', 'bundle.zip']
      await select(app, pilot, 'bundle.zip')
      await pilot.press('enter')
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'added.txt', 'note.md', 'bundle.zip', 'inside.txt']
      await pilot.press('left')
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'added.txt', 'note.md', 'bundle.zip']
      async def denied(*args, **kwargs):
        raise PermissionError('source unavailable')
      monkeypatch.setattr(fs, 'ls', denied)
      await select(app, pilot, 'child')
      await pilot.press('r')
      await settled(app, pilot)
      assert 'source unavailable' in str(app.query_one('#status', Static).content)
      assert labels(app) == [tmp_path.name, '.git', 'child', 'added.txt', 'note.md', 'bundle.zip']
  asyncio.run(exercise())


def test_tui_shows_the_catalog_as_a_tree_of_locations(tmp_path):
  async def exercise():
    outer = tmp_path / 'outer'
    inner = outer / 'inner'
    inner.mkdir(parents=True)
    (outer / 'a.txt').write_text('a')
    (inner / 'b.md').write_text('---\ntitle: B\n---\nText')
    folder = tmp_path / '.catalog'
    (folder / 'test-host').mkdir(parents=True)
    rows = [{'id': 1, 'path': 'outer', 'parent_file_location_id': None, 'root_path': str(outer),
        'index': str(outer / '.outer.gppufs.sqlite')},
      {'id': 2, 'path': 'inner', 'parent_file_location_id': 1, 'root_path': str(inner),
        'index': str(inner / '.inner.gppufs.sqlite')}]
    (folder / 'test-host' / 'locations.yaml').write_text(yaml.safe_dump(rows), encoding='utf-8')
    catalog = GppuCatalog(folder, host='test-host')
    app = HandlerBrowser(catalog)
    async with app.run_test(size=(130, 40)) as pilot:
      await settled(app, pilot)
      assert labels(app) == ['.catalog', 'outer']
      assert not (outer / '.outer.gppufs.sqlite').exists()
      await select(app, pilot, 'outer')
      assert app.current['gppu']['location']['id'] == 1
      await pilot.press('right')
      await settled(app, pilot)
      assert labels(app) == ['.catalog', 'outer', 'inner', 'a.txt']
      assert app.listing.location_addresses == {row['name'] for row in await catalog.ls()}
      await select(app, pilot, 'inner')
      await pilot.press('right')
      await settled(app, pilot)
      assert labels(app) == ['.catalog', 'outer', 'inner', 'b.md', 'a.txt']
      assert (inner / '.inner.gppufs.sqlite').is_file()
      await select(app, pilot, 'b.md')
      assert json.loads(app.query_one(TextArea).text)['gppu']['markdown']['title'] == 'B'
      assert cell(app, 'outer', 'files') == ''
      await select(app, pilot, 'outer')
      await pilot.press('r')
      await settled(app, pilot)
      assert (cell(app, 'outer', 'files'), cell(app, 'outer', 'folders')) == ('2', '1')
      assert cell(app, 'outer', 'indexed') == app.current['gppu']['probed_at'][:16]
      await select(app, pilot, '.catalog')
      await pilot.press('r')
      await settled(app, pilot)
      assert (app.current['gppu']['files'], app.current['gppu']['indexed'], app.current['gppu']['locations']) == (2, 2, 2)
      assert cell(app, '.catalog', 'indexed') == cell(app, 'outer', 'indexed')
  asyncio.run(exercise())


def test_tui_stays_responsive_while_a_listing_is_awaited(tmp_path):
  async def exercise():
    (tmp_path / 'note.txt').write_text('content')
    delegate = GppuFileSystem(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    class Filesystem:
      async def ls(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await delegate.ls(*args, **kwargs)
      async def info(self, *args, **kwargs):
        return await delegate.info(*args, **kwargs)
    app = HandlerBrowser(Filesystem())
    async with app.run_test(size=(130, 40)) as pilot:
      await asyncio.wait_for(entered.wait(), 5)
      await pilot.pause()
      assert labels(app)[1] == 'loading…'
      release.set()
      await settled(app, pilot)
      assert labels(app) == [tmp_path.name, 'note.txt']
  asyncio.run(exercise())
