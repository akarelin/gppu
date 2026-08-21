from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

SessionProvider = Literal['cc', 'cx', 'openclaw']
SessionRole = Literal['user', 'assistant']


class SessionFormatError(ValueError):
  pass


@dataclass(frozen=True)
class SessionTurn:
  role: SessionRole
  text: str
  timestamp: datetime | None


@dataclass(frozen=True)
class SessionFile:
  path: Path
  provider: SessionProvider
  session_ids: tuple[str, ...]
  records: tuple[dict[str, Any], ...]
  turns: tuple[SessionTurn, ...]
  span_start: datetime | None
  span_end: datetime | None

  @classmethod
  def from_path(cls, path: Path) -> SessionFile:
    records = cls._load_jsonl(path)
    provider = cls._identify_provider(path, records)
    timestamps = tuple(
      timestamp
      for record in records
      if (timestamp := cls._record_timestamp(record)) is not None
    )
    return cls(
      path=path,
      provider=provider,
      session_ids=cls._session_ids(provider, records),
      records=records,
      turns=cls._turns(provider, records),
      span_start=min(timestamps) if timestamps else None,
      span_end=max(timestamps) if timestamps else None,
    )

  @staticmethod
  def _load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
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

  @staticmethod
  def _identify_provider(
    path: Path,
    records: tuple[dict[str, Any], ...],
  ) -> SessionProvider:
    cx = any(
      record.get('type') in ('session_meta', 'response_item', 'event_msg')
      and isinstance(record.get('payload'), dict)
      for record in records
    )
    cc = any(
      isinstance(record.get('sessionId'), str)
      or record.get('type') in ('user', 'assistant')
      and isinstance(record.get('message'), dict)
      for record in records
    )
    openclaw = any(
      record.get('type') == 'session'
      and isinstance(record.get('id'), str)
      for record in records
    )
    providers: tuple[SessionProvider, ...] = tuple(
      provider
      for provider, recognized in (
        ('cx', cx),
        ('cc', cc),
        ('openclaw', openclaw),
      )
      if recognized
    )
    if len(providers) != 1:
      raise SessionFormatError(f'{path}: session format is not identifiable')
    return providers[0]

  @classmethod
  def _record_timestamp(cls, record: dict[str, Any]) -> datetime | None:
    values = [record.get('timestamp'), record.get('created_at')]
    for key in ('payload', 'snapshot'):
      nested = record.get(key)
      if isinstance(nested, dict):
        values.append(nested.get('timestamp'))
    return next(
      (
        parsed
        for value in values
        if (parsed := cls._parse_timestamp(value)) is not None
      ),
      None,
    )

  @staticmethod
  def _parse_timestamp(value: object) -> datetime | None:
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

  @staticmethod
  def _message_text(content: object) -> str:
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

  @classmethod
  def _message_turn(
    cls,
    role: object,
    content: object,
    timestamp: object,
  ) -> SessionTurn | None:
    if not isinstance(role, str):
      return None
    normalized_role = role.casefold()
    if normalized_role not in ('user', 'assistant'):
      return None
    text = cls._message_text(content)
    if not text.strip():
      return None
    return SessionTurn(
      role=normalized_role,
      text=text,
      timestamp=cls._parse_timestamp(timestamp),
    )

  @classmethod
  def _codex_turns(cls, records: tuple[dict[str, Any], ...]) -> tuple[SessionTurn, ...]:
    response_turns = []
    for record in records:
      payload = record.get('payload')
      if record.get('type') != 'response_item' or not isinstance(payload, dict):
        continue
      if payload.get('type') != 'message':
        continue
      turn = cls._message_turn(
        payload.get('role'),
        payload.get('content'),
        record.get('timestamp'),
      )
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
      turn = cls._message_turn(
        roles.get(payload.get('type')),
        payload.get('message'),
        record.get('timestamp'),
      )
      if turn is not None:
        event_turns.append(turn)
    return tuple(event_turns)

  @classmethod
  def _claude_turns(cls, records: tuple[dict[str, Any], ...]) -> tuple[SessionTurn, ...]:
    turns = []
    for record in records:
      if record.get('type') not in ('user', 'assistant') or record.get('isMeta') is True:
        continue
      message = record.get('message')
      if not isinstance(message, dict):
        continue
      turn = cls._message_turn(
        message.get('role'),
        message.get('content'),
        record.get('timestamp'),
      )
      if turn is not None:
        turns.append(turn)
    return tuple(turns)

  @classmethod
  def _openclaw_turns(cls, records: tuple[dict[str, Any], ...]) -> tuple[SessionTurn, ...]:
    turns = []
    for record in records:
      if record.get('type') != 'message':
        continue
      message = record.get('message')
      if not isinstance(message, dict):
        continue
      turn = cls._message_turn(
        message.get('role'),
        message.get('content'),
        record.get('timestamp'),
      )
      if turn is not None:
        turns.append(turn)
    return tuple(turns)

  @classmethod
  def _turns(
    cls,
    provider: SessionProvider,
    records: tuple[dict[str, Any], ...],
  ) -> tuple[SessionTurn, ...]:
    if provider == 'cx':
      return cls._codex_turns(records)
    if provider == 'cc':
      return cls._claude_turns(records)
    return cls._openclaw_turns(records)

  @staticmethod
  def _session_ids(
    provider: SessionProvider,
    records: tuple[dict[str, Any], ...],
  ) -> tuple[str, ...]:
    values = []
    for record in records:
      if provider == 'cx':
        payload = record.get('payload')
        value = (
          payload.get('id') or payload.get('session_id')
          if record.get('type') == 'session_meta' and isinstance(payload, dict)
          else None
        )
      elif provider == 'cc':
        value = record.get('sessionId')
      else:
        value = record.get('id') if record.get('type') == 'session' else None
      if isinstance(value, str) and value.strip():
        values.append(value.strip())
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class Session:
  source: Path
  files: tuple[SessionFile, ...]

  @classmethod
  def from_path(cls, source: Path) -> Session:
    if source.is_file():
      return cls(source=source, files=(SessionFile.from_path(source),))
    if source.is_dir():
      paths = sorted(
        (
          path
          for path in source.rglob('*')
          if path.is_file() and '.jsonl' in path.name.casefold()
        ),
        key=lambda path: str(path).casefold(),
      )
      return cls(
        source=source,
        files=tuple(SessionFile.from_path(path) for path in paths),
      )
    raise FileNotFoundError(source)


@dataclass(frozen=True)
class SessionStats:
  files: int
  sessions: int
  turns: int
  span_start: datetime | None
  span_end: datetime | None

  @classmethod
  def from_session(cls, session: Session) -> SessionStats:
    starts = tuple(
      file.span_start
      for file in session.files
      if file.span_start is not None
    )
    ends = tuple(
      file.span_end
      for file in session.files
      if file.span_end is not None
    )
    session_ids = {
      session_id
      for file in session.files
      for session_id in file.session_ids
    }
    return cls(
      files=len(session.files),
      sessions=len(session_ids),
      turns=sum(len(file.turns) for file in session.files),
      span_start=min(starts) if starts else None,
      span_end=max(ends) if ends else None,
    )
