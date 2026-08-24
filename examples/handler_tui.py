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

from gppu import Session, SessionMeta, handlers
from gppu.tui import FilesystemAdapter, LoaderMixin, TreeBrowser, TUIApp

LOGS_LISTED = 40


def fmt_span(span) -> str:
  if span is None:
    return '-'
  start, end = (moment.astimezone() for moment in span)
  return f'{start:%Y-%m-%d %H%M} - {end:%Y-%m-%d %H%M}'


def fmt_meta(meta: SessionMeta) -> str:
  return f'{fmt_span(meta.span):<32} {meta.turns:>6} turns  {", ".join(meta.models) or "-"}'


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
    sessions = handlers.load(self.path)
    what = f'[b]{sessions.agent}[/b], {len(sessions.files)} logs' if sessions else 'unrecognized'
    self.query_one('#status', Static).update(f'{escape(str(self.path))} - {what}')

  def action_probe(self) -> None:
    self.ask('probe', lambda sessions: [fmt_meta(sessions.meta())])

  def action_sessions(self) -> None:
    self.ask('sessions', lambda store: [
      f'{escape(Session.of(log).name)}'
      for log in store.files[:LOGS_LISTED]
    ])

  def ask(self, name, work) -> None:
    """Run a registry call off the UI thread, then render it."""
    path = self.path
    sessions = handlers.load(path)
    if sessions is None:
      self.query_one('#status', Static).update(f'{escape(str(path))} - unrecognized')
      return
    self.load_async(
      fetch=lambda: work(sessions),
      on_done=lambda lines: self.show(name, sessions, lines),
      status_id='#status',
      status_busy=f'{name} {path} …',
    )

  def show(self, name: str, sessions, lines: list[str]) -> None:
    detail = self.query_one('#detail', RichLog)
    detail.clear()
    detail.write(f'[b]{sessions.agent}[/b] {escape(str(sessions.path))}')
    for line in lines:
      detail.write(line)
    listed = min(len(sessions.files), LOGS_LISTED)
    shown = f'{listed} of {len(sessions.files)} logs' if name == 'sessions' else f'{len(sessions.files)} logs'
    self.query_one('#status', Static).update(f'{escape(str(sessions.path))} - {shown}')

  def cli(self) -> None:
    sessions = handlers.load(self.root)
    if sessions is None:
      print(f'{self.root}: unrecognized')
      return
    print(f'{self.root}: {sessions.agent}, {len(sessions.files)} logs')
    for log in sessions.files[:LOGS_LISTED]:
      print(Session.of(log).name)


if __name__ == '__main__':
  HandlerTUI.main(root=Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.cwd())
