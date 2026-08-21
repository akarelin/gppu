from __future__ import annotations

import json
from pathlib import Path

import pytest

from gppu.handlers import SessionFile, SessionFolder, SessionHandler


def _jsonl(path: Path, records: list[dict]) -> Path:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    ''.join(json.dumps(record) + '\n' for record in records),
    encoding='utf-8',
  )
  return path


def test_session_file_loads_complete_codex_object_and_derives_stats(tmp_path: Path) -> None:
  path = _jsonl(
    tmp_path / 'rollout.jsonl',
    [
      {
        'type': 'session_meta',
        'timestamp': '2026-08-20T01:00:00Z',
        'payload': {'id': 'session-one'},
      },
      {
        'type': 'response_item',
        'timestamp': '2026-08-20T01:01:00Z',
        'payload': {
          'type': 'message',
          'role': 'user',
          'content': [{'type': 'input_text', 'text': 'Question'}],
        },
      },
      {
        'type': 'response_item',
        'payload': {'type': 'function_call', 'name': 'shell'},
      },
      {
        'type': 'response_item',
        'timestamp': '2026-08-20T01:02:00Z',
        'payload': {
          'type': 'message',
          'role': 'assistant',
          'content': [{'type': 'output_text', 'text': 'Answer'}],
        },
      },
    ],
  )

  stats, obj = SessionHandler()(path)

  assert isinstance(obj, SessionFile)
  assert obj.provider == 'codex'
  assert obj.session_ids == ('session-one',)
  assert len(obj.records) == 4
  assert [(turn.role, turn.text) for turn in obj.turns] == [
    ('user', 'Question'),
    ('assistant', 'Answer'),
  ]
  assert stats.files == 1
  assert stats.sessions == 1
  assert stats.turns == 2
  assert stats.span_start.isoformat() == '2026-08-20T01:00:00+00:00'
  assert stats.span_end.isoformat() == '2026-08-20T01:02:00+00:00'


def test_session_folder_loads_every_jsonl_variant_and_derives_stats(tmp_path: Path) -> None:
  _jsonl(
    tmp_path / 'claude.jsonl.reset.1',
    [
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
        'message': {'role': 'assistant', 'content': 'Answer'},
      },
    ],
  )
  _jsonl(
    tmp_path / 'nested' / 'codex.jsonl',
    [
      {
        'type': 'session_meta',
        'timestamp': '2026-08-20T03:00:00Z',
        'payload': {'id': 'codex-one'},
      },
      {
        'type': 'event_msg',
        'timestamp': '2026-08-20T03:01:00Z',
        'payload': {'type': 'user_message', 'message': 'Question'},
      },
    ],
  )
  (tmp_path / 'ignored.txt').write_text('not a session', encoding='utf-8')

  stats, obj = SessionHandler()(tmp_path)

  assert isinstance(obj, SessionFolder)
  assert [file.provider for file in obj.files] == ['claude', 'codex']
  assert stats.files == 2
  assert stats.sessions == 2
  assert stats.turns == 3
  assert stats.span_start.isoformat() == '2026-08-20T02:00:00+00:00'
  assert stats.span_end.isoformat() == '2026-08-20T03:01:00+00:00'


def test_session_handler_reports_malformed_input(tmp_path: Path) -> None:
  path = tmp_path / 'bad.jsonl'
  path.write_text('not-json\n', encoding='utf-8')

  with pytest.raises(ValueError, match='bad.jsonl:1'):
    SessionHandler()(path)
