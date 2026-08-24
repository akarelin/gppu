from __future__ import annotations

import json
from pathlib import Path

import pytest

from gppu.handlers import handlers
from gppu.session import SessionMeta

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
    'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Question'}]},
  },
  {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell'}},
  {
    'type': 'response_item',
    'timestamp': '2026-08-20T01:02:00Z',
    'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Answer'}]},
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
    'message': {'role': 'assistant', 'model': 'claude-opus-5', 'content': [{'type': 'text', 'text': 'Answer'}]},
  },
]

OPENCLAW = [
  {'id': 'openclaw-one', 'modelId': 'anthropic/claude-opus-5', 'ts': 1787184000},
  {'type': 'message', 'ts': 1787184060, 'message': {'role': 'user', 'content': 'Question'}},
]


def _jsonl(path: Path, records: list[dict]) -> Path:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    ''.join(json.dumps(record) + '\n' for record in records),
    encoding='utf-8',
  )
  return path


def test_identifies_a_codex_store_and_spans_it(tmp_path: Path) -> None:
  _jsonl(tmp_path / '2026' / '08' / '20' / 'rollout.jsonl', CODEX)

  sessions = handlers.load(tmp_path)

  assert (sessions.agent, len(sessions.files)) == ('codex', 1)
  meta = sessions.meta()
  assert (meta.turns, meta.models) == (2, ('gpt-5.6',))
  assert [moment.isoformat() for moment in meta.span] == [
    '2026-08-20T01:00:00+00:00',
    '2026-08-20T01:02:00+00:00',
  ]


def test_identifies_a_claude_store(tmp_path: Path) -> None:
  _jsonl(tmp_path / 'D--Dev-gppu' / 'claude.jsonl', CLAUDE)

  sessions = handlers.load(tmp_path)
  meta = sessions.meta()

  assert sessions.agent == 'claude'
  assert (meta.turns, meta.models) == (2, ('claude-opus-5',))


def test_identifies_an_openclaw_store_and_reads_epoch_stamps(tmp_path: Path) -> None:
  _jsonl(tmp_path / 'agents' / 'alex' / 'sessions' / 'openclaw.jsonl', OPENCLAW)

  sessions = handlers.load(tmp_path)
  meta = sessions.meta()

  assert sessions.agent == 'openclaw'
  assert (meta.turns, meta.models) == (1, ('anthropic/claude-opus-5',))
  assert meta.span[0].isoformat() == '2026-08-20T00:00:00+00:00'


def test_identifies_hermes_and_agy_by_their_home_state_file(tmp_path: Path) -> None:
  hermes, agy = tmp_path / 'hermes', tmp_path / 'antigravity'
  (hermes / 'sessions').mkdir(parents=True)
  (hermes / 'state.db').write_bytes(b'SQLite format 3\x00')
  agy.mkdir()
  (agy / 'antigravity_state.pbtxt').write_text('installation {}', encoding='utf-8')

  assert handlers.load(hermes).agent == 'hermes'
  assert handlers.load(agy).agent == 'agy'


def test_a_folder_of_other_files_is_not_a_session_store(tmp_path: Path) -> None:
  (tmp_path / 'notes.txt').write_text('not a session', encoding='utf-8')
  _jsonl(tmp_path / 'data.jsonl', [{'name': 'row', 'value': 1}])

  assert handlers.identify(tmp_path) is None
  assert handlers.load(tmp_path) is None


def test_malformed_log_reports_its_line(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)
  path.write_text(path.read_text(encoding='utf-8') + 'not-json\n', encoding='utf-8')

  assert handlers.load(path).agent == 'codex'
  with pytest.raises(ValueError, match='rollout.jsonl:6'):
    SessionMeta.of(path)
