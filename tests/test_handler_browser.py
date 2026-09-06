"""Exercise the example with real local indexes and Textual keyboard input."""

import asyncio
import shutil
import threading
from pathlib import Path

from gppu.data import Persistence
from gppu.tui import TreeTable
from textual.widgets import DataTable, Static

from examples import handler_browser as browser


def test_index_first_refresh_and_unindexed_child(tmp_path, monkeypatch):
  async def exercise():
    note = tmp_path / 'note.md'
    note.write_text('---\ndate: 2026-09-05\n---\nA note.\n')
    child = tmp_path / 'child'
    child.mkdir()
    (child / 'new.txt').write_text('Unindexed child')
    live = await browser.read_folder(tmp_path)
    assert live['source'] == 'Filesystem'
    assert not (tmp_path / browser.INDEX_FILE).exists()

    indexed = await browser.read_folder(tmp_path, refresh=True)
    assert indexed['source'] == 'Index'
    assert 'markdown' in next(row for row in indexed['children'] if row['name'] == note.name)['handlers']
    assert indexed['root']['files'] == 1
    assert indexed['root']['folders'] == 1
    assert indexed['root']['span'] is not None
    note.unlink()
    (tmp_path / 'added.txt').write_text('Added after indexing')

    with monkeypatch.context() as patch:
      def unexpected_handler(*args, **kwargs):
        raise AssertionError('Indexed browsing must not invoke filesystem handlers')
      patch.setattr(browser, 'ListingHandler', unexpected_handler)
      assert await browser.read_folder(tmp_path) == indexed
    assert (await browser.read_folder(child))['source'] == 'Filesystem'

    refreshed = await browser.read_folder(tmp_path, refresh=True)
    names = {row['name'] for row in refreshed['children']}
    assert names == {'child', 'added.txt'}
    assert refreshed['root']['size'] == len('Added after indexing')
    assert await browser.read_folder(tmp_path) == refreshed

  asyncio.run(exercise())


def test_indexes_are_portable_and_preserve_other_namespaces(tmp_path):
  async def exercise():
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'hello.txt').write_text('hello')
    with Persistence(str(original), backend='sqlite') as index:
      index.upsert('OtherConsumer', 'key', {'value': 42})
    assert (await browser.read_folder(original))['source'] == 'Filesystem'
    await browser.read_folder(original, refresh=True)
    with Persistence(str(original), backend='sqlite') as index:
      assert index.load('OtherConsumer', 'key') == {'value': 42}
    copied = tmp_path / 'copied'
    shutil.copytree(original, copied)
    snapshot = await browser.read_folder(copied)
    assert snapshot['children'][0]['path'] == 'hello.txt'
    node = browser.entry(copied, snapshot['root'], snapshot['source'])
    assert node.id == str(copied)
    assert node.label == 'copied'

  asyncio.run(exercise())


def test_failed_refresh_preserves_previous_index(tmp_path, monkeypatch):
  async def exercise():
    (tmp_path / 'hello.txt').write_text('hello')
    previous = await browser.read_folder(tmp_path, refresh=True)
    (tmp_path / 'later.txt').write_text('later')

    def denied(*args, **kwargs):
      raise PermissionError('Index is read-only')

    with monkeypatch.context() as patch:
      patch.setattr(Persistence, 'upsert', denied)
      try:
        await browser.read_folder(tmp_path, refresh=True)
      except PermissionError as error:
        assert str(error) == 'Index is read-only'
      else:
        raise AssertionError('Write failure was hidden')
    assert await browser.read_folder(tmp_path) == previous

  asyncio.run(exercise())


def test_async_index_read_does_not_block_event_loop(tmp_path, monkeypatch):
  async def exercise():
    entered = threading.Event()
    release = threading.Event()
    original = browser.load_index

    def slow_read(folder):
      entered.set()
      assert release.wait(5), 'Event loop blocked on SQLite read'
      return original(folder)

    monkeypatch.setattr(browser, 'load_index', slow_read)
    task = asyncio.create_task(browser.read_folder(tmp_path))
    try:
      assert await asyncio.to_thread(entered.wait, 5)
      assert not task.done()
    finally:
      release.set()
    assert (await task)['source'] == 'Filesystem'

  asyncio.run(exercise())


def test_tui_expansion_index_refresh_and_error(tmp_path, monkeypatch):
  async def exercise():
    child = tmp_path / 'child'
    child.mkdir()
    (child / 'nested.txt').write_text('nested')
    (tmp_path / 'empty.txt').touch()
    app = browser.HandlerBrowser(tmp_path)
    async with app.run_test(size=(130, 30)) as pilot:
      await app.workers.wait_for_complete()
      await pilot.pause()
      tree = app.query_one(TreeTable)
      table = app.query_one(DataTable)
      assert table.row_count == 3
      assert table.get_row(str(tmp_path / 'empty.txt'))[-2] == ''
      table.focus()
      tree.select(str(child))
      await pilot.pause()
      assert tree.selected_entry.id == str(child)
      assert tree.selected_entry.is_container
      assert app.focused is table
      await pilot.press('right')
      await app.workers.wait_for_complete()
      await pilot.pause()
      assert table.row_count == 4
      expanded = tree.expanded_ids
      await pilot.press('i')
      await app.workers.wait_for_complete()
      await pilot.pause()
      assert tree.selected_entry.id == str(child)
      assert expanded == tree.expanded_ids
      assert tree.selected_entry.meta['source'] == 'Index'
      assert (child / browser.INDEX_FILE).exists()
      (child / 'added.txt').write_text('added')
      await pilot.press('i')
      await app.workers.wait_for_complete()
      await pilot.pause()
      assert table.row_count == 5
      assert tree.selected_entry.id == str(child)

      def denied(*args):
        raise PermissionError('Cannot write index')
      monkeypatch.setattr(browser, 'save_index', denied)
      await pilot.press('i')
      await app.workers.wait_for_complete()
      await pilot.pause()
      assert 'Cannot write index' in str(app.query_one('#status', Static).content)
      assert tree.selected_entry.meta['source'] == 'Index'
      assert not app.pending

  asyncio.run(exercise())
