"""Session stores — which agent wrote a folder of logs, and what is in them.

Identification is by evidence in the folder: the marker an agent's own
writer leaves in the first records of a session file (codex, claude,
openclaw), or the state file an agent keeps in its home (hermes, agy,
whose transcripts are not JSONL).

Everything else is generic — no per-agent parsing.  Span is the earliest
and latest timestamp anywhere in the records, models are any model id,
turns are the records carrying a user or assistant role.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .handlers import handlers

TIME_KEYS = ('timestamp', 'ts', 'started_at', 'session_start', 'time', 'created_at')
MODEL_KEYS = ('model', 'modelId')
ROLES = ('user', 'assistant')
SNIFF = 8

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
class SessionMeta:
  span: tuple[datetime, datetime] | None
  models: tuple[str, ...]
  turns: int

  @classmethod
  def of(cls, *paths: Path) -> SessionMeta:
    """Read every record of every file once: span, models, turns."""
    stamps, models, turns = [], [], 0
    for path in paths:
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
    return cls(
      span=(min(stamps), max(stamps)) if stamps else None,
      models=_uniq(models),
      turns=turns,
    )


@dataclass(frozen=True)
class Sessions:
  path: Path
  agent: str
  files: tuple[Path, ...]

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


def _uniq(values) -> tuple[str, ...]:
  return tuple(dict.fromkeys(
    value.strip() for value in values if isinstance(value, str) and value.strip()
  ))
