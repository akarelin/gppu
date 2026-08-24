"""Session handlers — Codex rollouts and Claude Code transcripts (JSONL).

Both providers write one JSON object per line, recognizable from the first
record.  Each reader returns a :class:`Session` for its own files and None
for everything else; :class:`SessionMeta` summarizes one or many of them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .handlers import handlers

_ROLES = ('user', 'assistant')
_TEXT_BLOCKS = ('text', 'input_text', 'output_text')


@dataclass(frozen=True)
class Turn:
  role: str
  text: str
  at: datetime | None


@dataclass(frozen=True)
class Session:
  path: Path
  provider: str
  ids: tuple[str, ...]
  models: tuple[str, ...]
  turns: tuple[Turn, ...]


@dataclass(frozen=True)
class SessionMeta:
  span: tuple[datetime, datetime] | None
  models: tuple[str, ...]
  turns: int

  @classmethod
  def of(cls, *sessions: Session) -> SessionMeta:
    stamps = sorted(turn.at for session in sessions for turn in session.turns if turn.at)
    return cls(
      span=(stamps[0], stamps[-1]) if stamps else None,
      models=_uniq(model for session in sessions for model in session.models),
      turns=sum(len(session.turns) for session in sessions),
    )


def _uniq(values) -> tuple[str, ...]:
  return tuple(dict.fromkeys(
    value.strip() for value in values if isinstance(value, str) and value.strip()
  ))


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


def _peek(path: Path) -> dict[str, Any]:
  """First record of a JSONL file; empty for anything else."""
  try:
    return next(_records(path), {})
  except (OSError, UnicodeDecodeError, ValueError):
    return {}


def _stamp(value: Any) -> datetime | None:
  if not isinstance(value, str):
    return None
  try:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))
  except ValueError:
    return None


def _text(content: Any) -> str:
  if isinstance(content, str):
    return content
  if not isinstance(content, list):
    return ''
  return '\n\n'.join(
    block['text'] for block in content
    if isinstance(block, dict)
    and block.get('type') in _TEXT_BLOCKS
    and isinstance(block.get('text'), str)
  )


def _turn(role: Any, content: Any, timestamp: Any) -> Turn | None:
  if role not in _ROLES:
    return None
  text = _text(content)
  return Turn(role, text, _stamp(timestamp)) if text.strip() else None


@handlers.add('codex')
def read_codex(path: Path) -> Session | None:
  """A Codex rollout: session_meta header, turn_context model, message items."""
  head = _peek(path)
  if head.get('type') != 'session_meta' or not isinstance(head.get('payload'), dict):
    return None
  ids, models, turns = [], [], []
  for record in _records(path):
    kind, payload = record.get('type'), record.get('payload')
    if not isinstance(payload, dict):
      continue
    if kind == 'session_meta':
      ids.append(payload.get('id'))
    elif kind == 'turn_context':
      models.append(payload.get('model'))
    elif kind == 'response_item' and payload.get('type') == 'message':
      turn = _turn(payload.get('role'), payload.get('content'), record.get('timestamp'))
      if turn:
        turns.append(turn)
  return Session(path, 'cx', _uniq(ids), _uniq(models), tuple(turns))


@handlers.add('claude')
def read_claude(path: Path) -> Session | None:
  """A Claude Code transcript: sessionId on every record, model on the message."""
  if not isinstance(_peek(path).get('sessionId'), str):
    return None
  ids, models, turns = [], [], []
  for record in _records(path):
    ids.append(record.get('sessionId'))
    message = record.get('message')
    if record.get('type') not in _ROLES or not isinstance(message, dict) or record.get('isMeta'):
      continue
    models.append(message.get('model'))
    turn = _turn(message.get('role'), message.get('content'), record.get('timestamp'))
    if turn:
      turns.append(turn)
  return Session(path, 'cc', _uniq(ids), _uniq(models), tuple(turns))
