"""Handlers — file readers registered by name, the way Jinja registers filters.

A handler is one function: give it a path, it returns an object for the
files it recognizes and ``None`` for everything else.  It registers itself
on the shared registry::

    from gppu.handlers import handlers

    @handlers.add('codex')
    def read_codex(path): ...

Callers ask the registry, never the handlers::

    handlers.identify(path)    # 'codex'
    handlers.load(path)        # the object that handler built

Nothing here knows about any particular kind of file; handlers live with
the objects they build (sessions in :mod:`gppu.session`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Reader = Callable[[Path], Any]


@dataclass
class Handlers:
  readers: dict[str, Reader] = field(default_factory=dict)

  def add(self, name: str) -> Callable[[Reader], Reader]:
    """Register a reader under `name`."""
    def register(read: Reader) -> Reader:
      self.readers[name] = read
      return read
    return register

  def identify(self, path: Path) -> str | None:
    """Name of the handler that claims this file."""
    return next((name for name, read in self.readers.items() if read(path) is not None), None)

  def load(self, path: Path) -> Any:
    """What the claiming handler makes of this file, or None."""
    return next((obj for read in self.readers.values() if (obj := read(path)) is not None), None)


handlers = Handlers()
