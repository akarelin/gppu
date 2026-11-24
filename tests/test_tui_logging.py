"""Logging uses the TUI panel while Textual owns the terminal."""
import importlib
import io
import logging

import pytest

pytest.importorskip('textual')
pytest.importorskip('pytest_asyncio')

from gppu.gppu import Logger
from gppu.tui import TUIApp


@pytest.mark.asyncio
async def test_console_retains_severity_and_class_method():
  core = importlib.import_module('gppu.gppu')

  class Operation(core.mixin_Logger):
    def fail(self):
      self.Error('operation failed')

  app = TUIApp()
  async with app.run_test():
    Operation().fail()
    message = next(line for line in app._debug_lines if 'operation failed' in line)
    assert 'Error' in message
    assert 'Operation.fail' in message
    assert 'gppu:' not in message
    app.debug('\x1b[31mError Collector.copy source failed\x1b[0m')
    assert app._debug_lines[-1] == 'Error Collector.copy source failed'

