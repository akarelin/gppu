"""Identify what a path holds, probe it for metadata, load its data.

A handler is a name plus three callables over a single file: ``identify``
(is this mine?), ``load`` (parse it into an object), ``meta`` (derive
metadata from that object).  ``probe`` is ``meta`` after ``load``.

Module-level ``identify``/``probe``/``load`` take a file or a folder and
route each file to the first handler that claims it.  Folder metadata is
the sum (``+``) of its files' metadata.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Any

from .session import SessionMeta, is_claude, is_codex, load_claude, load_codex


@dataclass(frozen=True)
class Handler:
  name: str
  identify: Callable[[Path], bool]
  load: Callable[[Path], Any]
  meta: Callable[[Any], Any]

  def probe(self, path: Path) -> Any:
    return self.meta(self.load(path))


HANDLERS: list[Handler] = []


def register(handler: Handler) -> Handler:
  HANDLERS.append(handler)
  return handler


def paths(path: Path) -> tuple[Path, ...]:
  """The file itself, or every file under the folder."""
  if path.is_file():
    return (path,)
  if path.is_dir():
    # ponytail: walks the whole tree up front; stream it if folders get big.
    return tuple(sorted(item for item in path.rglob('*') if item.is_file()))
  raise FileNotFoundError(path)


def claim(path: Path) -> Handler | None:
  """The handler for one file, or None when nothing recognizes it."""
  return next((handler for handler in HANDLERS if handler.identify(path)), None)


def identify(path: Path) -> Handler | None:
  """The handler for a file, or the first one claiming a file in a folder."""
  return next((handler for item in paths(path) if (handler := claim(item))), None)


def probe(path: Path) -> Any:
  """Metadata for a file, or the merged metadata of a folder's files."""
  metas = [handler.probe(item) for item in paths(path) if (handler := claim(item))]
  if not metas:
    raise ValueError(f'{path}: no handler')
  return reduce(operator.add, metas)


def load(path: Path) -> Any:
  """The object for a file, or a tuple of objects for a folder."""
  objects = tuple(handler.load(item) for item in paths(path) if (handler := claim(item)))
  if not objects:
    raise ValueError(f'{path}: no handler')
  return objects[0] if path.is_file() else objects


codex_handler = register(Handler('codex', is_codex, load_codex, SessionMeta.of))
claude_handler = register(Handler('claude', is_claude, load_claude, SessionMeta.of))
