"""LLM session logs: Codex rollouts and Claude Code transcripts (JSONL).

Both providers write one JSON object per line.  ``load_codex`` and
``load_claude`` turn a file into a :class:`Session`; ``SessionMeta.of``
derives span, models and turn count from it.  ``gppu.handlers`` wires
these into handlers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROLES = ('user', 'assistant')
TEXT_BLOCKS = ('text', 'input_text', 'output_text')
HEAD_RECORDS = 8


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
  def of(cls, session: Session) -> SessionMeta:
    stamps = sorted(turn.at for turn in session.turns if turn.at is not None)
    return cls(
      span=(stamps[0], stamps[-1]) if stamps else None,
      models=session.models,
      turns=len(session.turns),
    )

  def __add__(self, other: SessionMeta) -> SessionMeta:
    spans = [span for span in (self.span, other.span) if span is not None]
    return SessionMeta(
      span=(min(span[0] for span in spans), max(span[1] for span in spans)) if spans else None,
      models=unique(self.models + other.models),
      turns=self.turns + other.turns,
    )


def unique(values: tuple[Any, ...] | list[Any]) -> tuple[str, ...]:
  return tuple(dict.fromkeys(
    value.strip() for value in values if isinstance(value, str) and value.strip()
  ))


def records(path: Path) -> Iterator[dict[str, Any]]:
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


def head(path: Path) -> list[dict[str, Any]]:
  """First records of a JSONL file; whatever parsed, empty for anything else."""
  found = []
  try:
    for record in records(path):
      found.append(record)
      if len(found) >= HEAD_RECORDS:
        break
  except (OSError, UnicodeDecodeError, ValueError):
    pass
  return found


def is_codex(path: Path) -> bool:
  return any(
    record.get('type') == 'session_meta' and isinstance(record.get('payload'), dict)
    for record in head(path)
  )


def is_claude(path: Path) -> bool:
  return any(isinstance(record.get('sessionId'), str) for record in head(path))


def stamp(value: Any) -> datetime | None:
  if not isinstance(value, str):
    return None
  try:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))
  except ValueError:
    return None


def text_of(content: Any) -> str:
  if isinstance(content, str):
    return content
  if not isinstance(content, list):
    return ''
  return '\n\n'.join(
    block['text'] for block in content
    if isinstance(block, dict)
    and block.get('type') in TEXT_BLOCKS
    and isinstance(block.get('text'), str)
  )


def turn_of(role: Any, content: Any, timestamp: Any) -> Turn | None:
  if role not in ROLES:
    return None
  text = text_of(content)
  return Turn(role, text, stamp(timestamp)) if text.strip() else None


def load_codex(path: Path) -> Session:
  ids, models, turns = [], [], []
  for record in records(path):
    kind, payload = record.get('type'), record.get('payload')
    if not isinstance(payload, dict):
      continue
    if kind == 'session_meta':
      ids.append(payload.get('id'))
    elif kind == 'turn_context':
      models.append(payload.get('model'))
    elif kind == 'response_item' and payload.get('type') == 'message':
      turn = turn_of(payload.get('role'), payload.get('content'), record.get('timestamp'))
      if turn is not None:
        turns.append(turn)
  return Session(path, 'cx', unique(ids), unique(models), tuple(turns))


def load_claude(path: Path) -> Session:
  ids, models, turns = [], [], []
  for record in records(path):
    ids.append(record.get('sessionId'))
    message = record.get('message')
    if record.get('type') not in ROLES or not isinstance(message, dict) or record.get('isMeta'):
      continue
    models.append(message.get('model'))
    turn = turn_of(message.get('role'), message.get('content'), record.get('timestamp'))
    if turn is not None:
      turns.append(turn)
  return Session(path, 'cc', unique(ids), unique(models), tuple(turns))
