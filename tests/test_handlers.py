from __future__ import annotations

import json
import os
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

import pytest

from gppu.handlers import (
  typed,
  FileHandler,
  valid_time,
  FileStats,
  Record,
  SessionFile,
  SessionFolder,
  file_handler,
  session_handler,
)

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
    'uuid': 'one',
    'timestamp': '2026-08-20T02:00:00Z',
    'message': {'role': 'user', 'content': 'Question'},
  },
  {
    'type': 'assistant',
    'sessionId': 'claude-one',
    'uuid': 'two',
    'parentUuid': 'one',
    'timestamp': '2026-08-20T02:01:00Z',
    'message': {
      'role': 'assistant',
      'model': 'claude-opus-5',
      'content': [{'type': 'text', 'text': 'Answer'}],
    },
  },
]

OPENCLAW = [
  {'id': 'openclaw-one', 'modelId': 'anthropic/claude-opus-5', 'ts': 1787184000},
  {'type': 'message', 'ts': 1787184060, 'message': {'role': 'user', 'content': 'Question'}},
]

HERMES = [
  {
    'role': 'session_meta',
    'session_id': '20260512_035400_c197642b',
    'agent': 'main',
    'model': 'claude-opus-4-6',
    'platform': 'teams',
    'title': 'Testing the assistant',
    'started_at': '2026-05-12T10:54:00+00:00',
  },
  {'role': 'user', 'content': 'Question', 'timestamp': '2026-05-12T10:54:14+00:00'},
  {'role': 'assistant', 'content': 'Answer', 'timestamp': '2026-05-12T10:55:00+00:00'},
]

RAR = Path(r'C:\Program Files\WinRAR\Rar.exe')


def _chatgpt(uid: str, question: str = 'Question') -> dict:
  return {
    'id': uid,
    'title': question,
    'create_time': 1785585600,
    'update_time': 1785585720,
    'current_node': 'answer',
    'default_model_slug': 'gpt-5.6',
    'mapping': {
      'root': {'id': 'root', 'parent': None, 'message': None},
      'question': {
        'id': 'question',
        'parent': 'root',
        'message': {
          'author': {'role': 'user'},
          'create_time': 1785585660,
          'content': {'content_type': 'text', 'parts': [question]},
        },
      },
      'answer': {
        'id': 'answer',
        'parent': 'question',
        'message': {
          'author': {'role': 'assistant'},
          'create_time': 1785585720,
          'content': {'content_type': 'text', 'parts': ['Answer']},
          'metadata': {'model_slug': 'gpt-5.6'},
        },
      },
    },
  }


def _claude(uid: str) -> dict:
  return {
    'uuid': uid,
    'name': 'Question',
    'created_at': '2026-08-01T12:00:00Z',
    'updated_at': '2026-08-01T12:02:00Z',
    'chat_messages': [
      {
        'sender': 'human',
        'created_at': '2026-08-01T12:01:00Z',
        'content': [
          {'type': 'text', 'text': 'Question'},
          {'type': 'tool_use', 'name': 'ignored'},
        ],
      },
      {
        'sender': 'assistant',
        'created_at': '2026-08-01T12:02:00Z',
        'content': [{'type': 'text', 'text': 'Answer'}],
      },
    ],
  }


def _jsonl(path: Path, records: list[dict]) -> Path:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    ''.join(json.dumps(record) + '\n' for record in records),
    encoding='utf-8',
  )
  return path


def _iso(span) -> list[str]:
  return [moment.isoformat() for moment in span]


def test_session_handler_returns_stats_and_complete_object(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)

  stats, session = session_handler(path)

  assert isinstance(session, SessionFile)
  assert (session.harness, session.uid) == ('cx', 'codex-one')
  assert (len(session.turns), session.user_messages) == (2, ('Question',))
  assert session.models == ('gpt-5.6',)
  assert (stats.files, stats.sessions, stats.turns) == (1, 1, 2)
  assert _iso(stats.span) == [
    '2026-08-20T01:00:00+00:00',
    '2026-08-20T01:02:00+00:00',
  ]

  record = file_handler.probe(path, recursive=False)[0]
  assert record.handlers == ('session',)
  assert record.span == stats.span


def test_openai_export_chunks_are_one_session_collection(tmp_path: Path) -> None:
  path = tmp_path / 'openai.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('conversation_asset_file_names.json', '{}')
    archive.writestr('conversations-000.json', json.dumps([_chatgpt('chatgpt-one')]))
    archive.writestr('conversations-001.json', json.dumps([_chatgpt('chatgpt-two', 'Second')]))

  assert session_handler.identify(path) is True
  stats, sessions = session_handler(path)

  assert isinstance(sessions, SessionFolder)
  assert sessions.harness == 'chatgpt'
  assert [session.uid for session in sessions.files] == ['chatgpt-one', 'chatgpt-two']
  assert [session.path for session in sessions.files] == [
    PurePosixPath('conversations-000.json'),
    PurePosixPath('conversations-001.json'),
  ]
  assert all(session.location == path for session in sessions.files)
  assert sessions.files[0].user_messages == ('Question',)
  assert sessions.files[0].models == ('gpt-5.6',)
  assert (stats.files, stats.sessions, stats.turns, stats.bytes) == (1, 2, 4, path.stat().st_size)
  assert _iso(stats.span) == [
    '2026-08-01T12:00:00+00:00',
    '2026-08-01T12:02:00+00:00',
  ]
  assert file_handler.identify(path, recursive=False)[0].handlers == ('session', 'archive')


def test_anthropic_export_uses_flat_human_and_assistant_messages(tmp_path: Path) -> None:
  path = tmp_path / 'anthropic.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('projects.json', '[]')
    archive.writestr('conversations.json', json.dumps([_claude('claude-one')]))

  stats, sessions = session_handler(path)

  assert isinstance(sessions, SessionFolder)
  assert (sessions.harness, stats.sessions, stats.turns) == ('claude', 1, 2)
  assert sessions.files[0].uid == 'claude-one'
  assert sessions.files[0].user_messages == ('Question',)
  assert sessions.files[0].topic == 'Question'
  assert _iso(stats.span) == [
    '2026-08-01T12:00:00+00:00',
    '2026-08-01T12:02:00+00:00',
  ]


def test_named_conversation_export_with_unknown_shape_fails(tmp_path: Path) -> None:
  path = tmp_path / 'unknown.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('conversations.json', json.dumps([{'messages': []}]))

  assert session_handler.identify(path) is True
  with pytest.raises(ValueError, match='conversation format is not identifiable'):
    session_handler(path)


def test_session_topic_skips_machine_preamble_and_marks_internal_turns(tmp_path: Path) -> None:
  preamble = {
    **CLAUDE[0],
    'message': {'role': 'user', 'content': '<environment_context>machine</environment_context>'},
  }
  sidechain = {
    **CLAUDE[0],
    'uuid': 'sidechain',
    'isSidechain': True,
    'message': {'role': 'user', 'content': 'tool instruction'},
  }
  human = {
    **CLAUDE[0],
    'uuid': 'human',
    'message': {'role': 'user', 'content': 'Fix RDF: resizing'},
  }
  path = _jsonl(tmp_path / 'claude.jsonl', [preamble, sidechain, human, CLAUDE[1]])

  _, session = session_handler(path)

  assert isinstance(session, SessionFile)
  assert session.topic == 'Fix RDF resizing'
  assert session.user_messages == (
    '<environment_context>machine</environment_context>',
    'Fix RDF: resizing',
  )
  assert any(turn.sidechain for turn in session.turns)


def test_session_folder_supports_nested_codex_logs_and_state_markers(tmp_path: Path) -> None:
  codex = tmp_path / 'codex'
  _jsonl(codex / '2026' / '08' / '20' / 'rollout.jsonl', CODEX)
  stats, sessions = session_handler(codex)

  assert isinstance(sessions, SessionFolder)
  assert (sessions.harness, stats.files) == ('cx', 1)

  hermes = tmp_path / 'hermes'
  hermes.mkdir()
  (hermes / 'state.db').write_bytes(b'SQLite format 3\x00')
  stats, sessions = session_handler(hermes)

  assert isinstance(sessions, SessionFolder)
  assert (sessions.harness, stats.files) == ('hermes', 0)

  agy = tmp_path / 'agy'
  agy.mkdir()
  (agy / 'antigravity_state.pbtxt').write_text('installation {}', encoding='utf-8')
  stats, sessions = session_handler(agy)

  assert isinstance(sessions, SessionFolder)
  assert (sessions.harness, stats.files) == ('agy', 0)

  agy_cli = tmp_path / 'agy-cli'
  agy_cli.mkdir()
  (agy_cli / 'jetski_state.pbtxt').write_text('installation {}', encoding='utf-8')
  stats, sessions = session_handler(agy_cli)

  assert isinstance(sessions, SessionFolder)
  assert (sessions.harness, stats.files) == ('agy', 0)


def test_openclaw_and_teleported_claude_are_identified_from_content(tmp_path: Path) -> None:
  openclaw = _jsonl(tmp_path / 'openclaw.jsonl', OPENCLAW)
  teleported = _jsonl(tmp_path / 'teleported.jsonl', [{
    'type': 'teleported-from',
    'remoteSessionId': 'claude-remote',
    'timestamp': '2026-08-20T02:00:00Z',
  }])

  openclaw_stats, openclaw_session = session_handler(openclaw)
  _, claude_session = session_handler(teleported)

  assert isinstance(openclaw_session, SessionFile)
  assert (openclaw_session.harness, openclaw_session.uid) == ('openclaw', 'openclaw-one')
  assert (openclaw_stats.turns, openclaw_stats.models) == (1, ('anthropic/claude-opus-5',))
  assert isinstance(claude_session, SessionFile)
  assert (claude_session.harness, claude_session.uid) == ('cc', 'claude-remote')


def test_malformed_line_is_skipped_rather_than_failing_the_session(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)
  path.write_text(path.read_text(encoding='utf-8') + 'not-json\n', encoding='utf-8')

  _, session = session_handler(path)

  assert isinstance(session, SessionFile)
  assert len(session.records) == len(CODEX)


def test_codex_log_without_session_meta_remains_identifiable_but_has_no_uid(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'orphan.jsonl', CODEX[1:])

  _, session = session_handler(path)

  assert isinstance(session, SessionFile)
  assert (session.harness, session.uid) == ('cx', None)


def test_file_and_folder_records_have_handler_derived_spans(tmp_path: Path) -> None:
  first = tmp_path / 'first.txt'
  second = tmp_path / 'nested' / 'second.txt'
  first.write_text('one', encoding='utf-8')
  second.parent.mkdir()
  second.write_text('two', encoding='utf-8')
  first_time = datetime(2026, 8, 1, 12, tzinfo=timezone.utc).timestamp()
  second_time = datetime(2026, 9, 1, 12, tzinfo=timezone.utc).timestamp()
  os.utime(first, (first_time, first_time))
  os.utime(second, (second_time, second_time))

  records = file_handler.probe(tmp_path)
  found = {record.path: record for record in records}

  assert found[first].span[0].timestamp() == first_time
  assert found[second].span[1].timestamp() == second_time
  assert _iso(found[tmp_path].span) == [
    '2026-08-01T12:00:00+00:00',
    '2026-09-01T12:00:00+00:00',
  ]
  assert found[tmp_path].stats == FileStats(2, 1, 6, found[tmp_path].span)


def test_archive_files_and_folders_are_the_same_records(tmp_path: Path) -> None:
  path = tmp_path / 'logs.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    first = zipfile.ZipInfo('logs/first.txt', (2026, 8, 1, 12, 0, 0))
    second = zipfile.ZipInfo('logs/second.txt', (2026, 9, 1, 12, 0, 0))
    archive.writestr(first, 'one')
    archive.writestr(second, 'two')

  archive_record = file_handler.probe(path, recursive=False)[0]
  probe, = archive_record.probes
  records = probe.obj
  found = {record.path: record for record in records}

  assert all(isinstance(record, Record) for record in records)
  assert set(found) == {
    PurePosixPath('logs'),
    PurePosixPath('logs/first.txt'),
    PurePosixPath('logs/second.txt'),
  }
  assert all(record.location == path for record in records)
  assert found[PurePosixPath('logs')].is_folder
  assert found[PurePosixPath('logs')].stats.files == 2
  assert probe.stats.files == 2
  assert archive_record.span == probe.stats.span
  assert file_handler.children(archive_record) == (found[PurePosixPath('logs')],)
  assert file_handler.children(found[PurePosixPath('logs')]) == (
    found[PurePosixPath('logs/first.txt')],
    found[PurePosixPath('logs/second.txt')],
  )


def test_archive_name_comes_from_the_handler_hierarchy_span(tmp_path: Path) -> None:
  source = tmp_path / 'stage'
  source.mkdir()
  first = source / 'first.txt'
  last = source / 'last.txt'
  first.write_text('first', encoding='utf-8')
  last.write_text('last', encoding='utf-8')
  first_time = datetime(2026, 8, 1, 12, tzinfo=timezone.utc).timestamp()
  last_time = datetime(2026, 9, 1, 12, tzinfo=timezone.utc).timestamp()
  os.utime(first, (first_time, first_time))
  os.utime(last, (last_time, last_time))

  path = file_handler.archive_path(
    source,
    tmp_path / 'archives',
    'sessions',
    'rar',
    ZoneInfo('America/Los_Angeles'),
  )

  assert path.name == '260901_end-260801_start_sessions.rar'


@pytest.mark.skipif(not RAR.is_file(), reason='WinRAR is not installed')
def test_rar_handler_determines_the_final_archive_span(tmp_path: Path) -> None:
  source = tmp_path / 'session.jsonl'
  source.write_text('{}\n', encoding='utf-8')
  written = datetime(2026, 8, 20, 12, tzinfo=timezone.utc).timestamp()
  os.utime(source, (written, written))
  archive = tmp_path / 'sessions.rar'
  subprocess.run(
    [str(RAR), 'a', '-ep1', str(archive), str(source)],
    check=True,
    capture_output=True,
  )

  record = file_handler.probe(archive, recursive=False)[0]
  probe, = record.probes

  assert probe.stats == FileStats(1, 0, source.stat().st_size, probe.stats.span)
  assert probe.stats.span[0].astimezone(timezone.utc).date().isoformat() == '2026-08-20'


def test_probe_cache_is_invalidated_when_a_file_changes(tmp_path: Path) -> None:
  class CountingHandler:
    name = 'counting'

    def __init__(self) -> None:
      self.calls = 0

    def identify(self, path: Path) -> bool:
      return path.suffix == '.count'

    def __call__(self, path: Path):
      self.calls += 1
      stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
      return FileStats(1, 0, path.stat().st_size, (stamp, stamp)), path.read_text()

  selected = CountingHandler()
  handler = FileHandler(selected)
  path = tmp_path / 'one.count'
  path.write_text('one', encoding='utf-8')

  assert handler.probe(path, recursive=False)[0].probes[0].obj == 'one'
  assert handler.probe(path, recursive=False)[0].probes[0].obj == 'one'
  assert selected.calls == 1

  path.write_text('changed', encoding='utf-8')

  assert handler.probe(path, recursive=False)[0].probes[0].obj == 'changed'
  assert selected.calls == 2


def test_identify_navigation_and_normalize_use_the_same_records(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)
  identified = file_handler.identify(tmp_path)

  assert [record.path for record in identified] == [tmp_path, path]
  assert identified[0].stats is None
  assert identified[1].handlers == ('session',)
  assert file_handler.children(tmp_path)[0].metadata['path'] == str(path)

  _, session = session_handler(path)
  assert isinstance(session, SessionFile)
  destination = file_handler.normalize(path)

  assert destination.name == session.name
  assert destination.is_file() and not path.exists()


def test_normalize_copies_a_folder_hierarchy(tmp_path: Path) -> None:
  source = tmp_path / 'source'
  (source / 'nested').mkdir(parents=True)
  (source / 'nested' / 'one.txt').write_text('one', encoding='utf-8')
  destination = tmp_path / 'new' / 'copied'

  copied = file_handler.normalize(source, destination)

  assert copied == destination
  assert (destination / 'nested' / 'one.txt').read_text(encoding='utf-8') == 'one'


def test_session_span_uses_record_times_not_values_quoted_inside_content(tmp_path: Path) -> None:
  quoting = {
    **CODEX[3],
    'timestamp': '2026-08-20T01:03:00Z',
    'payload': {
      **CODEX[3]['payload'],
      'content': [{'type': 'output_text', 'text': 'old row', 'created_at': '2025-01-01T00:00:00Z'}],
    },
  }
  path = _jsonl(tmp_path / 'codex.jsonl', [*CODEX, quoting])

  _, session = session_handler(path)

  assert _iso(session.span) == ['2026-08-20T01:00:00+00:00', '2026-08-20T01:03:00+00:00']


def test_session_topic_skips_the_injected_agents_preamble(tmp_path: Path) -> None:
  preamble = {
    **CODEX[2],
    'payload': {
      **CODEX[2]['payload'],
      'content': [{'type': 'input_text', 'text': '# AGENTS.md instructions for D:\\_\n\n<INSTRUCTIONS>\nrules\n</INSTRUCTIONS>'}],
    },
  }
  path = _jsonl(tmp_path / 'codex.jsonl', [CODEX[0], CODEX[1], preamble, CODEX[2], CODEX[3]])

  _, session = session_handler(path)

  assert session.topic == 'Question'


def test_archive_member_without_a_stored_time_has_none_and_does_not_widen_the_span(tmp_path: Path) -> None:
  archive = tmp_path / 'bundle.zip'
  with zipfile.ZipFile(archive, 'w') as bundle:
    bundle.writestr(zipfile.ZipInfo('undated.txt'), 'x')
    dated = zipfile.ZipInfo('dated.txt', date_time=(2026, 8, 20, 1, 0, 0))
    bundle.writestr(dated, 'y')

  records = {record.path: record for record in file_handler.children(file_handler.probe(archive)[0])}

  assert records[PurePosixPath('undated.txt')].modified_at is None
  assert records[PurePosixPath('undated.txt')].span is None
  assert _iso(file_handler.probe(archive)[0].probes[0].stats.span) == [
    datetime(2026, 8, 20, 1, 0, 0).astimezone().isoformat(),
    datetime(2026, 8, 20, 1, 0, 0).astimezone().isoformat(),
  ]


def test_archive_root_and_absolute_member_names_are_listed_relative(tmp_path: Path) -> None:
  archive = tmp_path / 'rooted.zip'
  with zipfile.ZipFile(archive, 'w') as bundle:
    bundle.writestr(zipfile.ZipInfo('/'), '')
    bundle.writestr(zipfile.ZipInfo('/bin/tool.txt', date_time=(2026, 8, 20, 1, 0, 0)), 'x')

  records = {record.path: record for record in file_handler.probe(archive)[0].probes[0].obj}

  assert PurePosixPath('bin/tool.txt') in records
  assert PurePosixPath('.') not in records


def test_placeholder_and_future_times_are_not_times(tmp_path: Path) -> None:
  android = datetime(1981, 1, 1, 1, 1, 2).astimezone()
  assert valid_time(android) is None
  assert valid_time(datetime(1980, 1, 1).astimezone()) is None
  assert valid_time(datetime(1970, 1, 1, tzinfo=timezone.utc)) is None
  assert valid_time(datetime.now(timezone.utc) + timedelta(days=2)) is None
  real = datetime(1994, 10, 7, 3, 0, 54, tzinfo=timezone.utc)
  assert valid_time(real) == real

  archive = tmp_path / 'app.apk'
  with zipfile.ZipFile(archive, 'w') as bundle:
    bundle.writestr(zipfile.ZipInfo('AndroidManifest.xml', date_time=(1981, 1, 1, 1, 1, 2)), 'x')
  records = {record.path: record for record in file_handler.probe(archive)[0].probes[0].obj}
  assert records[PurePosixPath('AndroidManifest.xml')].modified_at is None
  assert file_handler.probe(archive)[0].probes[0].stats.span is None

  stale = tmp_path / 'zero.txt'
  stale.write_text('x', encoding='utf-8')
  os.utime(stale, (0, 0))
  assert file_handler.record(stale).modified_at is None


def test_human_messages_leave_out_generated_text_and_envelopes(tmp_path: Path) -> None:
  probe = {**CLAUDE[0], 'uuid': 'probe', 'message': {'role': 'user', 'content': 'Reply with exactly PONG'}}
  reminder = {**CLAUDE[0], 'uuid': 'reminder', 'message': {'role': 'user', 'content': '<system-reminder>context</system-reminder>'}}
  envelope = {**CLAUDE[0], 'uuid': 'envelope', 'message': {'role': 'user', 'content': 'Page: stuff\n\n## My request for Codex:\nSummarize the page'}}
  path = _jsonl(tmp_path / 'claude.jsonl', [probe, reminder, envelope, CLAUDE[1]])

  _, session = session_handler(path)

  assert isinstance(session, SessionFile)
  assert len(session.user_messages) == 3
  assert session.human_messages == ('Summarize the page',)
  assert session.topic == 'Summarize the page'
  assert typed('/clear') == ''
  assert typed('<realtime_delegation><input>Fix the light</input></realtime_delegation>') == 'Fix the light'


def test_session_of_generated_text_only_has_no_topic(tmp_path: Path) -> None:
  probe = {**CLAUDE[0], 'message': {'role': 'user', 'content': 'A command failed. Diagnose the error and fix it.'}}
  _, session = session_handler(_jsonl(tmp_path / 'claude.jsonl', [probe, CLAUDE[1]]))
  assert session.human_messages == ()
  assert session.topic == ''


def test_a_folder_that_will_not_be_listed_is_not_a_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  closed = tmp_path / 'closed'
  closed.mkdir()
  original = Path.iterdir

  def denied(self: Path):
    if self == closed:
      raise PermissionError(5, 'Access is denied')
    return original(self)

  monkeypatch.setattr(Path, 'iterdir', denied)
  assert session_handler.identify(closed) is False


def test_a_child_gone_between_the_listing_and_the_reading_is_not_a_child(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
  (tmp_path / 'here.txt').write_text('here', encoding='utf-8')
  (tmp_path / 'gone.txt').write_text('gone by the time it is read', encoding='utf-8')
  handler = FileHandler(session_handler)
  original = FileHandler.record

  def vanishing(self: FileHandler, path: Path) -> Record:
    if path.name == 'gone.txt':
      raise FileNotFoundError(2, 'The system cannot find the file specified', str(path))
    return original(self, path)

  monkeypatch.setattr(FileHandler, 'record', vanishing)
  assert [child.name for child in handler.children(tmp_path)] == ['here.txt']


def test_a_hermes_log_on_its_own_is_identified_from_its_content(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / '2026-05-12_main_20260512_035400_c197642b.jsonl', HERMES)

  assert session_handler.identify(path) is True
  stats, session = session_handler(path)
  assert (session.harness, session.uid) == ('hermes', '20260512_035400_c197642b')
  assert (len(session.turns), session.user_messages) == (2, ('Question',))
  assert _iso(stats.span) == ['2026-05-12T10:54:00+00:00', '2026-05-12T10:55:00+00:00']


def test_an_agy_transcript_and_its_session_folder_are_identified(tmp_path: Path) -> None:
  uid = '31053146-5556-492e-8342-872da1a8bcf9'
  path = _jsonl(
    tmp_path / 'brain' / uid / '.system_generated' / 'logs' / 'transcript_full.jsonl',
    [
      {
        'type': 'USER_INPUT',
        'source': 'USER_EXPLICIT',
        'status': 'DONE',
        'content': 'Question',
        'created_at': '2026-08-29T14:35:31Z',
      },
      {
        'type': 'PLANNER_RESPONSE',
        'source': 'MODEL',
        'status': 'DONE',
        'content': 'Answer',
        'created_at': '2026-08-29T14:49:31Z',
      },
    ],
  )

  stats, session = session_handler(path)

  assert session_handler.identify(path.parents[2]) is True
  assert (session.harness, session.uid) == ('agy', uid)
  assert (len(session.turns), session.user_messages) == (2, ('Question',))
  assert _iso(stats.span) == ['2026-08-29T14:35:31+00:00', '2026-08-29T14:49:31+00:00']

  folder_stats, folder = session_handler(path.parents[2])
  assert isinstance(folder, SessionFolder)
  assert (folder.harness, folder.uid) == ('agy', uid)
  assert folder_stats.sessions == 1
