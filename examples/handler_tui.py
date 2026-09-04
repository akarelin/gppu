#!/usr/bin/env python3
"""handler-tui — browse a tree, ask gppu.handlers what each path holds.

Run:  python examples/handler_tui.py [ROOT]

ROOT defaults to the current directory; point it at an agent's home to see
the session handler work:

    python examples/handler_tui.py ~/.codex/sessions
    python examples/handler_tui.py ~/.claude/projects

Every highlighted path is identified as you walk.  `p` probes the store for
span, models and turns, `s` lists the sessions it holds by the naming
convention.  Both run in a worker thread — they read every record of every
log under the path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, RichLog, Static

from gppu.handlers import SessionFile, SessionFolder, SessionHandler, SessionStats
from gppu.tui import FilesystemAdapter, LoaderMixin, TreeBrowser, TUIApp

LOGS_LISTED = 40
session_handler = SessionHandler()


def fmt_span(span) -> str:
  if span is None:
    return '-'
  start, end = (moment.astimezone() for moment in span)
  return f'{start:%Y-%m-%d %H%M} - {end:%Y-%m-%d %H%M}'


def fmt_meta(meta: SessionStats) -> str:
  return f'{fmt_span(meta.span):<32} {meta.turns:>6} turns  {", ".join(meta.models) or "-"}'


def session_files(obj: SessionFile | SessionFolder) -> tuple[SessionFile, ...]:
  return (obj,) if isinstance(obj, SessionFile) else obj.files


class HandlerTUI(LoaderMixin, TUIApp):
  """File manager over the handler registry: identify, probe, load."""

  TITLE = 'handler-tui'

  CSS = """
  #content { height: 1fr; }
  #tree { width: 46; border-right: solid $primary; height: 1fr; }
  #detail { height: 1fr; }
  .label { dock: top; height: 1; padding: 0 1; text-align: center; background: $boost; }
  #status { dock: bottom; height: 1; padding: 0 1; background: $boost; }
  """

  BINDINGS = [
    Binding('p', 'probe', 'Probe'),
    Binding('s', 'sessions', 'Sessions'),
    Binding('q', 'quit', 'Quit'),
  ]

  def __init__(self, root: Path) -> None:
    super().__init__()
    self.root = root
    self.path = root

  def compose(self) -> ComposeResult:
    with Horizontal(id='content'):
      yield TreeBrowser(adapter=FilesystemAdapter(str(self.root)), id='tree')
      with Vertical():
        yield Static('Detail', classes='label')
        yield RichLog(id='detail', markup=True, wrap=True)
    yield Static('', id='status')
    yield Footer()

  def on_mount(self) -> None:
    self.show_path()

  def on_tree_node_highlighted(self, event) -> None:
    entry = event.node.data
    if entry is None:
      return
    self.path = Path(entry.id)
    self.show_path()

  def show_path(self) -> None:
    if session_handler.identify(self.path):
      _, obj = session_handler(self.path)
      what = f'[b]{obj.harness}[/b], {len(session_files(obj))} logs'
    else:
      what = 'unrecognized'
    self.query_one('#status', Static).update(f'{escape(str(self.path))} - {what}')

  def action_probe(self) -> None:
    self.ask('probe', lambda result: [fmt_meta(result[0])])

  def action_sessions(self) -> None:
    self.ask('sessions', lambda result: [
      escape(session.name)
      for session in session_files(result[1])[:LOGS_LISTED]
    ])

  def ask(self, name, work) -> None:
    """Run a registry call off the UI thread, then render it."""
    path = self.path
    if not session_handler.identify(path):
      self.query_one('#status', Static).update(f'{escape(str(path))} - unrecognized')
      return
    self.load_async(
      fetch=lambda: session_handler(path),
      on_done=lambda result: self.show(name, result[1], work(result)),
      status_id='#status',
      status_busy=f'{name} {path} …',
    )

  def show(self, name: str, sessions, lines: list[str]) -> None:
    detail = self.query_one('#detail', RichLog)
    detail.clear()
    detail.write(f'[b]{sessions.harness}[/b] {escape(str(sessions.path))}')
    for line in lines:
      detail.write(line)
    files = session_files(sessions)
    listed = min(len(files), LOGS_LISTED)
    shown = f'{listed} of {len(files)} logs' if name == 'sessions' else f'{len(files)} logs'
    self.query_one('#status', Static).update(f'{escape(str(sessions.path))} - {shown}')

  def cli(self) -> None:
    if not session_handler.identify(self.root):
      print(f'{self.root}: unrecognized')
      return
    _, sessions = session_handler(self.root)
    files = session_files(sessions)
    print(f'{self.root}: {sessions.harness}, {len(files)} logs')
    for session in files[:LOGS_LISTED]:
      print(session.name)


if __name__ == '__main__':
  HandlerTUI.main(root=Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.cwd())
