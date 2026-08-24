"""Handlers — file readers registered by name, the way Jinja registers filters.

A handler is one function: give it a path, it returns an object for the
files it recognizes and ``None`` for everything else.  It registers itself
on the shared registry::

    from gppu.handlers import handlers

    @handlers.add('codex')
    def read_codex(path): ...

Callers ask the registry, never the handlers::

    handlers.identify(path)    # 'sessions'
    handlers.load(path)        # the object that handler built

The registry knows about no particular kind of file; each handler lives
beside the object it builds.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


# Session stores — which agent wrote a folder of logs, and what is in them.
#
# Identification is by evidence in the folder: the marker an agent's own
# writer leaves in the first records of a session file (codex, claude,
# openclaw), or the state file an agent keeps in its home (hermes, agy,
# whose transcripts are not JSONL).
#
# Everything else is generic — no per-agent parsing.  Span is the earliest
# and latest timestamp anywhere in the records, models are any model id,
# turns are the records carrying a user or assistant role, uid is the
# session id the writer stamped, topic is the first thing the user said.

TIME_KEYS = ('timestamp', 'ts', 'started_at', 'session_start', 'time', 'created_at')
MODEL_KEYS = ('model', 'modelId')
ID_KEYS = ('sessionId', 'session_id', 'id')
ROLES = ('user', 'assistant')
SNIFF = 8  # records sniffed for an agent marker
PREAMBLE = 3  # lines of a user message searched for a machine tag
UNITS = (('d', 86400), ('h', 3600), ('m', 60), ('s', 1))
UNSAFE = '\\/:*?"<>|\r\n\t'
NAME_LIMIT = 254

MARKERS = {
  'codex': lambda record: record.get('type') == 'session_meta',
  'claude': lambda record: isinstance(record.get('sessionId'), str),
  'openclaw': lambda record: isinstance(record.get('modelId'), str),
}

HOMES = {
  'hermes': 'state.db',
  'agy': 'antigravity_state.pbtxt',
}


@dataclass(frozen=True)
class Session:
  """One log: when it ran, how long, how many turns, and what it was about."""

  path: Path
  uid: str | None
  span: tuple[datetime, datetime] | None
  models: tuple[str, ...]
  turns: int
  topic: str

  @classmethod
  def of(cls, path: Path) -> Session:
    """Read every record of a log once: uid, span, models, turns, topic."""
    stamps, models, turns, uid, topic = [], [], 0, None, ''
    for record in _records(path):
      scopes = [
        scope for scope in (record, record.get('payload'), record.get('message'))
        if isinstance(scope, dict)
      ]
      stamps += [
        stamp for scope in scopes for key in TIME_KEYS
        if (stamp := _stamp(scope.get(key)))
      ]
      models += [scope.get(key) for scope in scopes for key in MODEL_KEYS]
      turns += any(scope.get('role') in ROLES for scope in scopes)
      uid = uid or _first(scopes, ID_KEYS)
      topic = topic or _topic(scopes)
    return cls(
      path=path,
      uid=uid,
      span=(min(stamps), max(stamps)) if stamps else None,
      models=_uniq(models),
      turns=turns,
      topic=topic,
    )

  @property
  def length(self) -> str:
    """`~3h` — last message to first in one unit; empty for a single moment."""
    if self.span is None:
      return ''
    seconds = round((self.span[1] - self.span[0]).total_seconds())
    if not seconds:
      return ''
    unit, size = next(pair for pair in UNITS if seconds >= pair[1])
    return f'~{round(seconds / size)}{unit}'

  @property
  def label(self) -> str:
    """`260822-0232 12~3h - Fix RDF resizing` — start, turns, span, topic."""
    start = f'{self.span[0].astimezone():%y%m%d-%H%M} ' if self.span else ''
    topic = f' - {self.topic}' if self.topic else ''
    return f'{start}{self.turns}{self.length}{topic}'

  @property
  def name(self) -> str:
    """Filename by convention; only the topic is truncated to fit the limit."""
    tail = (f'.{self.uid}' if self.uid else '') + self.path.suffix
    label = self.label
    if len(label) + len(tail) > NAME_LIMIT:
      label = label[:NAME_LIMIT - len(tail)].rstrip()
    return f'{label}{tail}'


@dataclass(frozen=True)
class SessionMeta:
  """Span, models and turns across a whole store."""

  span: tuple[datetime, datetime] | None
  models: tuple[str, ...]
  turns: int

  @classmethod
  def of(cls, *paths: Path) -> SessionMeta:
    sessions = [Session.of(path) for path in paths]
    spans = [session.span for session in sessions if session.span]
    return cls(
      span=(min(span[0] for span in spans), max(span[1] for span in spans)) if spans else None,
      models=_uniq([model for session in sessions for model in session.models]),
      turns=sum(session.turns for session in sessions),
    )


@dataclass(frozen=True)
class Sessions:
  path: Path
  agent: str
  files: tuple[Path, ...]

  def sessions(self) -> tuple[Session, ...]:
    """Every session the store holds, one per log."""
    return tuple(Session.of(file) for file in self.files)

  def meta(self) -> SessionMeta:
    """Span, models and turns across every log in the store."""
    return SessionMeta.of(*self.files)


@handlers.add('sessions')
def read_sessions(path: Path) -> Sessions | None:
  """A session store: the agent that wrote it and the JSONL logs it holds."""
  if path.is_file():
    agent = _agent(path)
    return Sessions(path, agent, (path,)) if agent else None
  files = tuple(sorted(path.rglob('*.jsonl')))
  agent = next((found for file in files if (found := _agent(file))), None) or next(
    (name for name, marker in HOMES.items() if (path / marker).exists()), None)
  return Sessions(path, agent, files) if agent else None


def _agent(path: Path) -> str | None:
  """The agent whose marker shows up in the first records of a log."""
  head = _head(path)
  return next(
    (name for name, marker in MARKERS.items() if any(marker(record) for record in head)),
    None,
  )


def _records(path: Path) -> Iterator[dict[str, Any]]:
  """Every JSON object in a JSONL file, by line."""
  with path.open('r', encoding='utf-8') as stream:
    for number, line in enumerate(stream, 1):
      if not line.strip():
        continue
      try:
        record = json.loads(line)
      except json.JSONDecodeError as error:
        raise ValueError(f'{path}:{number}: {error.msg}') from error
      if isinstance(record, dict):
        yield record


def _head(path: Path) -> list[dict[str, Any]]:
  """First records of a JSONL file; whatever parsed, empty for anything else."""
  found = []
  try:
    for record in _records(path):
      found.append(record)
      if len(found) >= SNIFF:
        break
  except (OSError, UnicodeDecodeError, ValueError):
    pass
  return found


def _stamp(value: Any) -> datetime | None:
  if isinstance(value, str):
    try:
      return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
      return None
  if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 1_000_000_000:
    seconds = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(seconds, timezone.utc)
  return None


def _first(scopes: list[dict[str, Any]], keys: tuple[str, ...]) -> str | None:
  """The first of `keys` any scope carries as a string, keys in preference order."""
  return next(
    (value for key in keys for scope in scopes
     if isinstance(value := scope.get(key), str) and value),
    None,
  )


def _topic(scopes: list[dict[str, Any]]) -> str:
  """First line the user wrote, filesystem-safe; a machine preamble is not one."""
  said = next((scope.get('content') for scope in scopes if scope.get('role') == 'user'), None)
  if isinstance(said, list):
    said = '\n'.join(
      part['text'] for part in said
      if isinstance(part, dict) and isinstance(part.get('text'), str)
    )
  if not isinstance(said, str) or not said.strip():
    return ''
  lines = said.strip().splitlines()
  if any(line.startswith('<') and line.endswith('>') for line in lines[:PREAMBLE]):
    return ''
  return ' '.join(''.join(' ' if char in UNSAFE else char for char in lines[0]).split())


def _uniq(values) -> tuple[str, ...]:
  return tuple(dict.fromkeys(
    value.strip() for value in values if isinstance(value, str) and value.strip()
  ))
