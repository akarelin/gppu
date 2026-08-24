#!/usr/bin/env python3
"""handler-tui — browse a tree, ask gppu.handlers what each path holds.

Run:  python examples/handler_tui.py [ROOT]

ROOT defaults to the current directory; point it at a session store to see
the registered handlers work:

    python examples/handler_tui.py ~/.codex/sessions
    python examples/handler_tui.py ~/.claude/projects

Every highlighted file is identified as you walk.  `p` probes the
highlighted file or folder for metadata, `l` loads its objects.  Both run
in a worker thread — probing a folder parses every session under it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, RichLog, Static

from gppu.handlers import identify, load, probe
from gppu.tui import FilesystemAdapter, LoaderMixin, TreeBrowser, TUIApp


def fmt_span(span) -> str:
  if span is None:
    return '-'
  start, end = (moment.astimezone() for moment in span)
  return f'{start:%Y-%m-%d %H%M} - {end:%Y-%m-%d %H%M}'


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
    Binding('l', 'load', 'Load'),
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
    handler = identify(self.path) if self.path.is_file() else None
    what = handler.name if handler else ('folder' if self.path.is_dir() else 'unrecognized')
    self.query_one('#status', Static).update(f'{self.path} - [b]{what}[/b]')

  def action_probe(self) -> None:
    self.run('probe', probe)

  def action_load(self) -> None:
    self.run('load', load)

  def run(self, name, work) -> None:
    path = self.path
    self.load_async(
      fetch=lambda: work(path),
      on_done=lambda result: self.show(name, path, result),
      status_id='#status',
      status_busy=f'{name} {path} …',
    )

  def show(self, name: str, path: Path, result) -> None:
    detail = self.query_one('#detail', RichLog)
    detail.clear()
    detail.write(f'[b]{name}[/b] {escape(str(path))}')
    if name == 'probe':
      detail.write(f'span   {fmt_span(result.span)}')
      detail.write(f'models {", ".join(result.models) or "-"}')
      detail.write(f'turns  {result.turns}')
      self.query_one('#status', Static).update(f'{path} - {result.turns} turns')
      return
    sessions = result if isinstance(result, tuple) else (result,)
    for session in sessions:
      models = ', '.join(session.models) or '-'
      detail.write(f'{session.provider} {escape(session.path.name)} - {len(session.turns)} turns, {models}')
    if len(sessions) == 1:
      detail.write('')
      for turn in sessions[0].turns[:20]:
        at = f'{turn.at.astimezone():%H%M}' if turn.at else '····'
        detail.write(f'[dim]{at}[/dim] [b]{turn.role}[/b] {escape(turn.text[:200])}')
    self.query_one('#status', Static).update(f'{path} - {len(sessions)} loaded')

  def cli(self) -> None:
    handler = identify(self.root)
    print(f'{self.root}: {handler.name if handler else "unrecognized"}')
    if handler is not None:
      meta = probe(self.root)
      print(f'span   {fmt_span(meta.span)}')
      print(f'models {", ".join(meta.models)}')
      print(f'turns  {meta.turns}')


if __name__ == '__main__':
  HandlerTUI.main(root=Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.cwd())
