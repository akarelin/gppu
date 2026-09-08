"""Logging uses the TUI panel while Textual owns the terminal."""
import importlib
import io
import logging

import pytest

pytest.importorskip('textual')
pytest.importorskip('pytest_asyncio')

from gppu import Env, TRACE_RULES
from gppu.tui import TUIApp


@pytest.mark.asyncio
async def test_tui_preserves_file_and_trace_rules_without_writing_to_terminal(tmp_path):
  core = importlib.import_module('gppu.gppu')
  previous_rules = dict(TRACE_RULES)
  Env.reset()
  path = tmp_path / 'tui.log'
  Env.from_dict({'log_file': str(path), 'trace_rules': {'all': False}})
  console = io.StringIO()
  original = core._sh.setStream(console)
  app = TUIApp()
  try:
    async with app.run_test():
      core.Info('WBLUE', 'panel message', 'NONE', 'value')
      core.Debug('hidden trace')
      assert console.getvalue() == ''
      assert any('panel message value' in line for line in app._debug_lines)
      assert not any('hidden trace' in line for line in app._debug_lines)
      assert 'panel message value' in path.read_text()
      assert 'hidden trace' not in path.read_text()
      TRACE_RULES['all'] = True
      core.Debug('visible trace')
      assert any('visible trace' in line for line in app._debug_lines)
      assert 'visible trace' in path.read_text()
    core.Info('terminal restored')
    assert 'terminal restored' in console.getvalue()
    assert app._log_handler not in logging.getLogger().handlers
  finally:
    core._sh.setStream(original)
    Env.reset()
    TRACE_RULES.clear()
    TRACE_RULES.update(previous_rules)


@pytest.mark.asyncio
async def test_shared_log_and_config_screens_update_while_app_runs():
  Env.reset()
  Env.from_dict({'screen_test': 'configured'})
  app = TUIApp()
  async with app.run_test() as pilot:
    await pilot.press('ctrl+o')
    log = app.screen.query_one('#debug-output')
    before = len(log.lines)
    app.debug('arrived after the log screen opened')
    await pilot.pause(0.3)
    assert len(log.lines) > before
    await pilot.press('escape', 'ctrl+g')
    assert app.screen.query_one('#info-panel').display
    await pilot.press('escape')
  Env.reset()
