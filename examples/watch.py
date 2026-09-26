"""A TUI app: the same parameters and Connections as a CLI app, and main runs on the screen's loop.

  watch --interval 0.5
"""
import asyncio

from textual.widgets import Log

from gppu.tui import TUIApp


class Watch(TUIApp):
  def compose(self): yield Log()

  async def main(self, interval: float = 1.0, count: int = 10) -> None:
    """Write a line every interval seconds."""
    for n in range(count):
      self.query_one(Log).write_line(f'tick {n}')
      await asyncio.sleep(interval)


if __name__ == '__main__': Watch.cli()
