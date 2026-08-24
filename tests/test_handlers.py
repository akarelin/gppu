from __future__ import annotations

import json
from pathlib import Path

import pytest

from gppu.handlers import handlers
from gppu.session import Session, SessionMeta

CODEX = [
  {
    'type': 'session_meta',
    'timestamp': '2026-08-20T01:00:00Z',
    'payload': {'id': 'codex-one'},
  },
  {'type': 'turn_context', 'payload': {'model': 'gpt-5.6'}},
  {
    'type': 'response_item',
    'timestamp': '2026-08-20T01:01:00Z',
    'payload': {
      'type': 'message',
      'role': 'user',
      'content': [{'type': 'input_text', 'text': 'Question'}],
    },
  },
  {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell'}},
  {
    'type': 'response_item',
    'timestamp': '2026-08-20T01:02:00Z',
    'payload': {
      'type': 'message',
      'role': 'assistant',
      'content': [{'type': 'output_text', 'text': 'Answer'}],
    },
  },
]

CLAUDE = [
  {
    'type': 'user',
    'sessionId': 'claude-one',
    'timestamp': '2026-08-20T02:00:00Z',
    'message': {'role': 'user', 'content': 'Question'},
  },
  {
    'type': 'assistant',
    'sessionId': 'claude-one',
    'timestamp': '2026-08-20T02:01:00Z',
    'message': {
      'role': 'assistant',
      'model': 'claude-opus-5',
      'content': [{'type': 'text', 'text': 'Answer'}],
    },
  },
]


def _jsonl(path: Path, records: list[dict]) -> Path:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    ''.join(json.dumps(record) + '\n' for record in records),
    encoding='utf-8',
  )
  return path


def test_identifies_and_probes_a_codex_file(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)

  assert handlers.identify(path) == 'codex'
  session = handlers.load(path)
  meta = SessionMeta.of(session)
  assert meta.turns == 2
  assert meta.models == ('gpt-5.6',)
  assert [span.isoformat() for span in meta.span] == [
    '2026-08-20T01:01:00+00:00',
    '2026-08-20T01:02:00+00:00',
  ]

  assert isinstance(session, Session)
  assert session.provider == 'cx'
  assert session.ids == ('codex-one',)
  assert [(turn.role, turn.text) for turn in session.turns] == [
    ('user', 'Question'),
    ('assistant', 'Answer'),
  ]


def test_identifies_and_probes_a_claude_file(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'claude.jsonl', CLAUDE)

  assert handlers.identify(path) == 'claude'
  session = handlers.load(path)
  meta = SessionMeta.of(session)
  assert (meta.turns, meta.models) == (2, ('claude-opus-5',))
  assert session.provider == 'cc'
  assert session.ids == ('claude-one',)


def test_folder_merges_metadata_of_every_session_it_holds(tmp_path: Path) -> None:
  _jsonl(tmp_path / 'rollout.jsonl', CODEX)
  _jsonl(tmp_path / 'nested' / 'claude.jsonl', CLAUDE)
  (tmp_path / 'ignored.txt').write_text('not a session', encoding='utf-8')

  meta = SessionMeta.of(*handlers.scan(tmp_path))

  assert meta.turns == 4
  assert meta.models == ('claude-opus-5', 'gpt-5.6')
  assert [span.isoformat() for span in meta.span] == [
    '2026-08-20T01:01:00+00:00',
    '2026-08-20T02:01:00+00:00',
  ]
  assert [session.provider for session in handlers.scan(tmp_path)] == ['cc', 'cx']


def test_unrecognized_file_has_no_handler(tmp_path: Path) -> None:
  path = tmp_path / 'notes.txt'
  path.write_text('not a session', encoding='utf-8')

  assert handlers.identify(path) is None
  assert handlers.load(path) is None
  assert handlers.scan(path) == ()


def test_malformed_session_file_reports_its_line(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'bad.jsonl', CODEX)
  path.write_text(path.read_text(encoding='utf-8') + 'not-json\n', encoding='utf-8')

  with pytest.raises(ValueError, match='bad.jsonl:6'):
    handlers.load(path)
