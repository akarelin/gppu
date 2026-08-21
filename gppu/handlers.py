from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

ObjectT = TypeVar('ObjectT')
StatsT = TypeVar('StatsT')


class Handler(ABC, Generic[ObjectT, StatsT]):
  def __call__(self, source: Path) -> tuple[StatsT, ObjectT]:
    obj = self.load(source)
    return self.stats(obj), obj

  @abstractmethod
  def load(self, source: Path) -> ObjectT: ...

  @abstractmethod
  def stats(self, obj: ObjectT) -> StatsT: ...


@dataclass(frozen=True)
class SessionTurn:
  role: Literal['user', 'assistant']
  text: str
  timestamp: datetime | None


@dataclass(frozen=True)
class SessionFile:
  path: Path
  provider: Literal['claude', 'codex']
  session_ids: tuple[str, ...]
  records: tuple[dict[str, Any], ...]
  turns: tuple[SessionTurn, ...]
  span_start: datetime | None
  span_end: datetime | None


@dataclass(frozen=True)
class SessionFolder:
  path: Path
  files: tuple[SessionFile, ...]


SessionObject = SessionFile | SessionFolder


@dataclass(frozen=True)
class SessionStats:
  files: int
  sessions: int
  turns: int
  span_start: datetime | None
  span_end: datetime | None


def _records(path: Path) -> tuple[dict[str, Any], ...]:
  records = []
  with path.open('r', encoding='utf-8') as stream:
    for line_number, line in enumerate(stream, 1):
      if not line.strip():
        continue
      try:
        value = json.loads(line)
      except json.JSONDecodeError as error:
        raise ValueError(f'{path}:{line_number}: {error.msg}') from error
      if not isinstance(value, dict):
        raise ValueError(f'{path}:{line_number}: session record must be an object')
      records.append(value)
  if not records:
    raise ValueError(f'{path}: session file is empty')
  return tuple(records)


def _provider(path: Path, records: tuple[dict[str, Any], ...]) -> Literal['claude', 'codex']:
  codex = any(
    record.get('type') in ('session_meta', 'response_item', 'event_msg')
    and isinstance(record.get('payload'), dict)
    for record in records
  )
  claude = any(
    isinstance(record.get('sessionId'), str)
    or record.get('type') in ('user', 'assistant')
    and isinstance(record.get('message'), dict)
    for record in records
  )
  if codex == claude:
    raise ValueError(f'{path}: session format is not identifiable')
  return 'codex' if codex else 'claude'


def _timestamp(value: object) -> datetime | None:
  if isinstance(value, bool) or value is None:
    return None
  if isinstance(value, (int, float)):
    seconds = float(value)
    if seconds > 100_000_000_000:
      seconds /= 1000
    try:
      return datetime.fromtimestamp(seconds, timezone.utc)
    except (OSError, OverflowError, ValueError):
      return None
  if not isinstance(value, str) or not value.strip():
    return None
  try:
    parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
  except ValueError:
    return None
  return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _record_timestamp(record: dict[str, Any]) -> datetime | None:
  values = [record.get('timestamp'), record.get('created_at')]
  for key in ('payload', 'snapshot'):
    nested = record.get(key)
    if isinstance(nested, dict):
      values.append(nested.get('timestamp'))
  return next((parsed for value in values if (parsed := _timestamp(value)) is not None), None)


def _text(content: object) -> str:
  if isinstance(content, str):
    return content
  if not isinstance(content, list):
    return ''
  parts = []
  for block in content:
    if isinstance(block, str):
      text = block
    elif isinstance(block, dict) and block.get('type') in ('text', 'input_text', 'output_text'):
      text = block.get('text')
    else:
      text = None
    if isinstance(text, str) and text.strip():
      parts.append(text)
  return '\n\n'.join(parts)


def _turn(role: object, content: object, timestamp: object) -> SessionTurn | None:
  if not isinstance(role, str):
    return None
  role = role.casefold()
  if role not in ('user', 'assistant'):
    return None
  text = _text(content)
  if not text.strip():
    return None
  return SessionTurn(role=role, text=text, timestamp=_timestamp(timestamp))


def _codex_turns(records: tuple[dict[str, Any], ...]) -> tuple[SessionTurn, ...]:
  response_turns = []
  for record in records:
    payload = record.get('payload')
    if record.get('type') != 'response_item' or not isinstance(payload, dict):
      continue
    if payload.get('type') != 'message':
      continue
    turn = _turn(payload.get('role'), payload.get('content'), record.get('timestamp'))
    if turn is not None:
      response_turns.append(turn)
  if response_turns:
    return tuple(response_turns)

  event_turns = []
  roles = {'user_message': 'user', 'agent_message': 'assistant'}
  for record in records:
    payload = record.get('payload')
    if record.get('type') != 'event_msg' or not isinstance(payload, dict):
      continue
    role = roles.get(payload.get('type'))
    turn = _turn(role, payload.get('message'), record.get('timestamp'))
    if turn is not None:
      event_turns.append(turn)
  return tuple(event_turns)


def _claude_turns(records: tuple[dict[str, Any], ...]) -> tuple[SessionTurn, ...]:
  turns = []
  for record in records:
    if record.get('type') not in ('user', 'assistant') or record.get('isMeta') is True:
      continue
    message = record.get('message')
    if not isinstance(message, dict):
      continue
    turn = _turn(message.get('role'), message.get('content'), record.get('timestamp'))
    if turn is not None:
      turns.append(turn)
  return tuple(turns)


def _session_ids(provider: str, records: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
  values = []
  for record in records:
    if provider == 'codex':
      payload = record.get('payload')
      value = (
        payload.get('id') or payload.get('session_id')
        if record.get('type') == 'session_meta' and isinstance(payload, dict)
        else None
      )
    else:
      value = record.get('sessionId')
    if isinstance(value, str) and value.strip():
      values.append(value.strip())
  return tuple(dict.fromkeys(values))


class SessionHandler(Handler[SessionObject, SessionStats]):
  def load(self, source: Path) -> SessionObject:
    source = Path(source)
    if source.is_file():
      return self._file(source)
    if source.is_dir():
      paths = sorted(
        (
          path for path in source.rglob('*')
          if path.is_file() and '.jsonl' in path.name.casefold()
        ),
        key=lambda path: str(path).casefold(),
      )
      return SessionFolder(path=source, files=tuple(self._file(path) for path in paths))
    raise FileNotFoundError(source)

  def stats(self, obj: SessionObject) -> SessionStats:
    files = (obj,) if isinstance(obj, SessionFile) else obj.files
    starts = [file.span_start for file in files if file.span_start is not None]
    ends = [file.span_end for file in files if file.span_end is not None]
    session_ids = {
      session_id
      for file in files
      for session_id in file.session_ids
    }
    return SessionStats(
      files=len(files),
      sessions=len(session_ids),
      turns=sum(len(file.turns) for file in files),
      span_start=min(starts) if starts else None,
      span_end=max(ends) if ends else None,
    )

  @staticmethod
  def _file(path: Path) -> SessionFile:
    records = _records(path)
    provider = _provider(path, records)
    timestamps = [
      timestamp
      for record in records
      if (timestamp := _record_timestamp(record)) is not None
    ]
    return SessionFile(
      path=path,
      provider=provider,
      session_ids=_session_ids(provider, records),
      records=records,
      turns=_codex_turns(records) if provider == 'codex' else _claude_turns(records),
      span_start=min(timestamps) if timestamps else None,
      span_end=max(timestamps) if timestamps else None,
    )
