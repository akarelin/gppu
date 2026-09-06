from __future__ import annotations

import asyncio
import json
import threading
import zipfile

from textual.widgets import DataTable, Static, TextArea

from examples.handler_browser import HandlerBrowser
from gppu.handlers import GppuFileSystem


async def settled(app, pilot):
  await app.workers.wait_for_complete()
  await pilot.pause()
  await app.workers.wait_for_complete()


def test_tui_navigation_metadata_refresh_and_errors(tmp_path, monkeypatch):
  async def exercise():
    child = tmp_path / 'child'
    child.mkdir()
    (child / 'note.md').write_text('---\ntitle: Metadata in the TUI\n---\nText')
    with zipfile.ZipFile(tmp_path / 'bundle.zip', 'w') as archive:
      archive.writestr('inside.txt', 'inside')
    fs = GppuFileSystem(tmp_path)
    app = HandlerBrowser(fs)
    async with app.run_test(size=(130, 35)) as pilot:
      await settled(app, pilot)
      table = app.query_one(DataTable)
      assert table.row_count == 2
      child_row = next(i for i, value in enumerate(app.rows.values()) if value['gppu']['name'] == 'child')
      table.move_cursor(row=child_row)
      await pilot.press('enter')
      await settled(app, pilot)
      assert app.current['gppu']['name'] == 'child'
      assert table.row_count == 1
      detail = json.loads(app.query_one(TextArea).text)
      assert detail['gppu']['markdown']['title'] == 'Metadata in the TUI'
      (child / 'added.txt').write_text('added')
      await pilot.press('r')
      await settled(app, pilot)
      assert table.row_count == 2
      await pilot.press('backspace')
      await settled(app, pilot)
      assert app.current['name'] == fs.info()['name']
      archive_row = next(i for i, value in enumerate(app.rows.values()) if value['gppu']['name'] == 'bundle.zip')
      table.move_cursor(row=archive_row)
      await pilot.press('enter')
      await settled(app, pilot)
      assert table.row_count == 1
      assert next(iter(app.rows.values()))['gppu']['name'] == 'inside.txt'
      await pilot.press('backspace')
      await settled(app, pilot)
      assert app.current['name'] == fs.info()['name']
      def denied(*args, **kwargs):
        raise PermissionError('source unavailable')
      monkeypatch.setattr(fs, 'ls', denied)
      await pilot.press('r')
      await settled(app, pilot)
      assert 'source unavailable' in str(app.query_one('#status', Static).content)
      assert table.row_count == 2
  asyncio.run(exercise())


def test_tui_io_runs_outside_event_loop(tmp_path):
  async def exercise():
    (tmp_path / 'note.txt').write_text('content')
    delegate = GppuFileSystem(tmp_path)
    entered, release = threading.Event(), threading.Event()
    class Filesystem:
      def ls(self, *args, **kwargs):
        entered.set()
        assert release.wait(5), 'Filesystem I/O blocked the UI event loop'
        return delegate.ls(*args, **kwargs)
      def info(self, *args, **kwargs):
        return delegate.info(*args, **kwargs)
    app = HandlerBrowser(Filesystem())
    async with app.run_test(size=(130, 35)) as pilot:
      try:
        assert await asyncio.to_thread(entered.wait, 5)
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 0
      finally:
        release.set()
      await settled(app, pilot)
      assert app.query_one(DataTable).row_count == 1
  asyncio.run(exercise())
