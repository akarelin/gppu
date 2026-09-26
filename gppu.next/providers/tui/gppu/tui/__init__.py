"""gppu.tui — provider: a Textual screen on an AsyncApp.

TUIApp is an AsyncApp, so a TUI is started, configured and given Connections exactly as a service is, and anything
a service does — ``_spawn``, MQTT, timers — runs on the same loop as the screen. ``main`` runs once the screen is
mounted and may run for as long as the screen does; quitting the screen cancels what is still running.

    class Browser(TUIApp):
      def compose(self): yield Log()
      async def main(self, folder: Path = Path('.'), db: Postgres = 'pg-lake'):
        for row in db.rows('select ...'): self.query_one(Log).write_line(str(row))

    if __name__ == '__main__': Browser.cli()

The widgets, the launcher and the sidecar move here unchanged from gppu/tui; they are not repeated in the mock-up.
"""
from __future__ import annotations

from typing import Any

from textual.app import App as TextualApp
from textual.binding import Binding

from gppu import AsyncApp


class TUIApp(AsyncApp, TextualApp):
  """A Textual application that is a gppu AsyncApp. ``q`` quits; ``done(result)`` quits with a result."""

  BINDINGS = [Binding('q', 'done', 'Quit', show=False)]

  def __init__(self, name: str = '') -> None:
    super().__init__(name)
    self._params: dict[str, Any] = {}

  async def main(self, **params: Any) -> Any: return None

  async def invoke(self, **given: Any) -> Any:
    self._params = self.params(**given)
    async with self._task_scope():
      result = await TextualApp.run_async(self)
      await self.stop()
      return result

  def on_mount(self) -> None: self._spawn(self.main(**self._params))

  def action_done(self) -> None: self.done()

  def done(self, result: Any = None) -> None: self.exit(result=result)
