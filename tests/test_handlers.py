from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
import gppu.fs.handlers as handlers_module
from gppu import TimeSpan

from gppu.fs.handlers import (
  HANDLERS,
  CSVHandler,
  EmailHandler,
  FolderHandler,
  Handler,
  LogHandler,
  MarkdownHandler,
  Record,
  Session,
  SessionFolderHandler,
  SessionHandler,
  SessionTurn,
  SqliteHandler,
  probe,
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

AGY_UID = '31053146-5556-492e-8342-872da1a8bcf9'
AGY = [
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
]


def _jsonl(path: Path, records: list[dict]) -> Path:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    ''.join(json.dumps(record) + '\n' for record in records),
    encoding='utf-8',
  )
  return path


def _bounds(span) -> tuple[datetime, datetime]:
  assert isinstance(span, TimeSpan)
  return span.start, span.end


def _iso(span) -> list[datetime]:
  return list(_bounds(span))


def test_session_handler_reads_a_codex_session(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)

  session = SessionHandler.parse(path)

  assert isinstance(session, Session)
  assert (session.type, session.uid) == ('cx', 'codex-one')
  assert (session.data['turns'], session.data['topic'], session.name) == (2, 'Question', 'Question')
  record = probe(path)
  assert HANDLERS[record.type] is SessionHandler


def test_a_codex_session_names_no_models(tmp_path: Path) -> None:
  # Codex is read as Linked Data's sessions read it, and they read no model from turn_context.
  session = SessionHandler.parse(_jsonl(tmp_path / 'rollout.jsonl', CODEX))

  assert 'models' not in session.data


def test_a_codex_session_spans_its_session_messages(tmp_path: Path) -> None:
  # A session's span is its session messages', as Linked Data's: from the first user or agent message, not session_meta.
  session = SessionHandler.parse(_jsonl(tmp_path / 'rollout.jsonl', CODEX))

  assert _iso(session.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-20T01:01:00+00:00',
    '2026-08-20T01:02:00+00:00',
  ]]


def test_session_probe_checks_extension_and_size(tmp_path: Path) -> None:
  unsupported = tmp_path / 'rollout.json'
  unsupported.write_text(json.dumps(CODEX[0]), encoding='utf-8')
  empty = tmp_path / 'empty.jsonl'
  empty.touch()
  supported = _jsonl(tmp_path / 'rollout.JSONL', CODEX)

  assert probe(unsupported).type == 'file'
  assert probe(empty).type == 'file'
  assert probe(supported).type == 'session'


def test_session_folder_probe_takes_harness_homes_by_their_path(tmp_path: Path) -> None:
  folder = tmp_path / 'sessions'
  _jsonl(folder / 'nested.jsonl', CODEX)

  assert probe(folder).type == 'folder'
  for home in ('.hermes', '.gemini/antigravity', '.gemini/antigravity-cli'):
    (tmp_path / home).mkdir(parents=True)
    assert probe(tmp_path / home).type == 'sessionfolder'


def test_a_session_folder_is_told_by_its_path_not_by_what_it_holds(tmp_path: Path) -> None:
  folder = tmp_path / 'sessions'
  _jsonl(folder / 'nested.jsonl', CODEX)
  (folder / 'state.db').touch()
  hermes = tmp_path / '.hermes'
  hermes.mkdir()

  assert probe(folder).type == 'folder'
  assert probe(hermes).type == 'sessionfolder'


def test_an_empty_folder_is_a_folder_holding_nothing(tmp_path: Path) -> None:
  record = probe(tmp_path)
  folder = FolderHandler.parse(tmp_path)

  assert HANDLERS[record.type] is FolderHandler
  assert (folder.data['files'], folder.data['folders'], folder.data['bytes'], folder.span) == (0, 0, 0, None)


def test_handlers_module_constructs_no_handler_objects() -> None:
  constructed = {
    name: value
    for name, value in vars(handlers_module).items()
    if isinstance(value, Handler)
  }

  assert constructed == {}


def test_markdown_handler_preserves_frontmatter_and_derives_standard_fields(
  tmp_path: Path,
) -> None:
  path = tmp_path / 'Fallback filename.md'
  path.write_text(
    '''---
name: Display name
tags:
  - meta
  - handlers
created: 2026-08-27T19:42
updated: 2026-09-01T05:11
unknown:
  nested: value
---
# Body
''',
    encoding='utf-8',
  )

  markdown = MarkdownHandler.parse(path)

  assert markdown.status == 'parsed'
  assert markdown.data['frontmatter'] == {
    'name': 'Display name',
    'tags': ['meta', 'handlers'],
    'created': '2026-08-27T19:42',
    'updated': '2026-09-01T05:11',
    'unknown': {'nested': 'value'},
  }
  assert (markdown.data['title'], markdown.name, markdown.data['tags']) == (
    'Display name',
    'Display name',
    ['meta', 'handlers'],
  )
  assert _iso(markdown.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-27T19:42:00-07:00',
    '2026-09-01T05:11:00-07:00',
  ]]
  assert markdown.meta['size'] == path.stat().st_size
  assert probe(path).type == 'markdown'


def test_markdown_handler_uses_filename_without_frontmatter(tmp_path: Path) -> None:
  path = tmp_path / 'Plain file.md'
  path.write_text('# Plain file\n', encoding='utf-8')

  markdown = MarkdownHandler.parse(path)

  assert markdown.data['frontmatter'] == {}
  assert (markdown.data['title'], markdown.name, markdown.data['tags'], markdown.span) == (
    'Plain file',
    'Plain file',
    [],
    None,
  )


def test_markdown_handler_rejects_invalid_frontmatter_mapping(tmp_path: Path) -> None:
  path = tmp_path / 'invalid.md'
  path.write_text('---\n- not\n- a mapping\n---\n', encoding='utf-8')

  with pytest.raises(ValueError, match='frontmatter must be a mapping'):
    MarkdownHandler.parse(path)


def test_csv_handler_reads_header_and_every_row(tmp_path: Path) -> None:
  path = tmp_path / 'table.csv'
  path.write_text('title,tags\nOne,"a,b"\nTwo,c\n', encoding='utf-8')

  table = CSVHandler.parse(path)

  assert table.status == 'parsed'
  assert table.data['header'] == ['title', 'tags']
  assert table.data['rows'] == 2
  assert (table.meta['size'], table.span) == (path.stat().st_size, None)
  assert probe(path).type == 'csv'


def test_csv_handler_derives_span_and_allows_subclass_time_format(
  tmp_path: Path,
) -> None:
  class BillingCSVHandler(CSVHandler):
    time_keys = (*CSVHandler.time_keys, 'billed_at')
    time_formats = (*CSVHandler.time_formats, '%m/%d/%Y %H:%M')

  path = tmp_path / 'billing.csv'
  path.write_text(
    'title,billed_at,timestamp\n'
    'First,08/27/2026 19:42,\n'
    'Second,,2026-09-01T05:11:00-07:00\n',
    encoding='utf-8',
  )

  table = BillingCSVHandler.parse(path)

  assert _iso(table.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-27T19:42:00-07:00',
    '2026-09-01T05:11:00-07:00',
  ]]


def test_a_log_is_probed_as_a_log(tmp_path: Path) -> None:
  path = tmp_path / 'service.log'
  path.write_text('[2026-09-04T08:00:00-07:00] started\n', encoding='utf-8')

  assert HANDLERS[probe(path).type] is LogHandler


def test_log_handler_uses_timestamped_rows_for_span(tmp_path: Path) -> None:
  path = tmp_path / 'service.log'
  path.write_text(
    '[2026-09-04T08:00:00-07:00] started\n'
    'continuation without a timestamp\n'
    '2026-09-04 09:15:30,500 finished\n',
    encoding='utf-8',
  )

  log = LogHandler.parse(path)

  assert _iso(log.span) == [datetime.fromisoformat(value) for value in [
    '2026-09-04T08:00:00-07:00',
    '2026-09-04T09:15:30.500000-07:00',
  ]]
  assert log.meta['size'] == path.stat().st_size


@pytest.mark.parametrize(
  ('filename', 'timestamp', 'subject', 'party', 'collision'),
  (
    (
      '110628.155519 - Fertilize Invoice - Alon Sahar.msg',
      '2011-06-28T15:55:19-07:00',
      'Fertilize Invoice',
      'Alon Sahar',
      None,
    ),
    (
      '110628.155519 - Fertilize Invoice - Alon Sahar - 1.msg',
      '2011-06-28T15:55:19-07:00',
      'Fertilize Invoice',
      'Alon Sahar',
      1,
    ),
    (
      "110628.211159 - Guests' flight schedule - Kimberly Ramos.eml",
      '2011-06-28T21:11:59-07:00',
      "Guests' flight schedule",
      'Kimberly Ramos',
      None,
    ),
    (
      '110629.191106 - Re- International SIM card - Eric Wong.msg',
      '2011-06-29T19:11:06-07:00',
      'Re- International SIM card',
      'Eric Wong',
      None,
    ),
  ),
)
def test_email_handler_derives_filename_metadata_without_parsing_message(
  tmp_path: Path,
  filename: str,
  timestamp: str,
  subject: str,
  party: str,
  collision: int | None,
) -> None:
  path = tmp_path / filename
  path.write_bytes(b'email payload is intentionally not parsed')

  email = EmailHandler.parse(path)

  assert email.status == 'parsed'
  assert email.data['subject'] == subject
  assert email.data['party'] == party
  assert email.data.get('collision') == collision
  assert email.data['timestamp'].isoformat() == timestamp
  assert _bounds(email.span) == (email.data['timestamp'], email.data['timestamp'])
  assert probe(path).type == 'email'


def test_email_handler_accepts_a_filename_without_declared_metadata(
  tmp_path: Path,
) -> None:
  path = tmp_path / 'message.EML'
  path.write_bytes(b'payload')

  email = EmailHandler.parse(path)

  assert probe(path).type == 'email'
  assert email.data == {}
  assert email.span is None


def test_ignored_paths_are_probed_and_no_handler_reads_them(tmp_path: Path) -> None:
  git_folder = tmp_path / '.git'
  cache_folder = tmp_path / '.cache'
  git_folder.mkdir()
  cache_folder.mkdir()
  (git_folder / 'config').write_text('not a repository', encoding='utf-8')
  (cache_folder / 'cached.txt').write_text('cached', encoding='utf-8')
  ignored_file = tmp_path / 'scratch.tmp'
  retained_file = tmp_path / 'retained.txt'
  ignored_file.write_text('scratch', encoding='utf-8')
  retained_file.write_text('retained', encoding='utf-8')

  assert {path.name: probe(path).type for path in tmp_path.iterdir()} == {
    '.git': 'ignored',
    '.cache': 'ignored',
    'scratch.tmp': 'ignored',
    'retained.txt': 'file',
  }
  assert 'ignored' not in HANDLERS


def _topic_session(tmp_path: Path) -> Path:
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
  return _jsonl(tmp_path / 'claude.jsonl', [preamble, sidechain, human, CLAUDE[1]])


def test_session_name_skips_machine_preamble_and_internal_turns(tmp_path: Path) -> None:
  session = SessionHandler.parse(_topic_session(tmp_path))

  assert session.data['turns'] == 4
  assert session.data['normalized_name'].endswith(' - Fix RDF resizing.claude-one.jsonl')


def test_a_claude_code_topic_is_its_first_prompt(tmp_path: Path) -> None:
  # data.topic is Linked Data's: the first line of the first prompt, a sidechain's among them; the name a person
  # typed is normalized_name's.
  session = SessionHandler.parse(_topic_session(tmp_path))

  assert session.data['topic'] == 'tool instruction'


def test_claude_subagent_is_identified_by_its_agent_id(tmp_path: Path) -> None:
  # A subagent transcript carries its parent's sessionId on every record and its own agentId,
  # which is what the file is named after. Without the agent id every subagent in a session
  # answers with the parent's id and denies being one.
  subagent = [
    {**record, 'agentId': 'a067dda7f881a582d', 'isSidechain': True} for record in CLAUDE
  ]
  path = _jsonl(tmp_path / 'agent-a067dda7f881a582d.jsonl', subagent)

  session = SessionHandler.parse(path)

  assert isinstance(session, Session)
  assert (session.uid, session.meta.get('parent_uid'), session.data['subagent']) == (
    'a067dda7f881a582d', 'claude-one', True
  )

  plain = SessionHandler.parse(_jsonl(tmp_path / 'claude.jsonl', CLAUDE))
  assert (plain.uid, plain.meta.get('parent_uid'), plain.data['subagent']) == ('claude-one', None, False)


def test_session_folder_supports_nested_codex_logs_and_state_markers(tmp_path: Path) -> None:
  codex = tmp_path / 'codex'
  _jsonl(codex / '2026' / '08' / '20' / 'rollout.jsonl', CODEX)
  sessions = SessionFolderHandler.parse(codex)

  assert sessions.status == 'parsed'
  assert probe(codex).type == 'folder'
  assert (sessions.type, sessions.data['harness'], sessions.data['sessions'], sessions.data['uid']) == (
    'sessionfolder', 'cx', 1, 'codex-one'
  )

  hermes = tmp_path / 'hermes'
  hermes.mkdir()
  (hermes / 'state.db').write_bytes(b'SQLite format 3\x00')
  sessions = SessionFolderHandler.parse(hermes)

  assert (sessions.data['harness'], sessions.data['sessions']) == ('hermes', 0)

  agy = tmp_path / 'agy'
  agy.mkdir()
  (agy / 'antigravity_state.pbtxt').write_text('installation {}', encoding='utf-8')
  sessions = SessionFolderHandler.parse(agy)

  assert (sessions.data['harness'], sessions.data['sessions']) == ('agy', 0)

  agy_cli = tmp_path / 'agy-cli'
  agy_cli.mkdir()
  (agy_cli / 'jetski_state.pbtxt').write_text('installation {}', encoding='utf-8')
  sessions = SessionFolderHandler.parse(agy_cli)

  assert (sessions.data['harness'], sessions.data['sessions']) == ('agy', 0)


def _teleported(tmp_path: Path) -> Path:
  return _jsonl(tmp_path / 'teleported.jsonl', [{
    'type': 'teleported-from',
    'remoteSessionId': 'claude-remote',
    'timestamp': '2026-08-20T02:00:00Z',
  }])


def test_openclaw_and_teleported_claude_are_identified_from_content(tmp_path: Path) -> None:
  openclaw_session = SessionHandler.parse(_jsonl(tmp_path / 'openclaw.jsonl', OPENCLAW))
  claude_session = SessionHandler.parse(_teleported(tmp_path))

  assert (openclaw_session.type, openclaw_session.uid) == ('openclaw', 'openclaw-one')
  assert (openclaw_session.data['turns'], openclaw_session.data['models']) == (1, ['anthropic/claude-opus-5'])
  assert claude_session.type == 'cc'


def test_a_teleported_claude_session_is_its_remote_session(tmp_path: Path) -> None:
  assert SessionHandler.parse(_teleported(tmp_path)).uid == 'claude-remote'


def test_malformed_line_is_skipped_rather_than_failing_the_session(tmp_path: Path) -> None:
  clean = SessionHandler.parse(_jsonl(tmp_path / 'clean.jsonl', CODEX))
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)
  path.write_text(path.read_text(encoding='utf-8') + 'not-json\n', encoding='utf-8')

  session = SessionHandler.parse(path)

  assert isinstance(session, Session)
  assert (session.type, session.uid, session.data) == ('cx', 'codex-one', clean.data)
  assert _bounds(session.span) == _bounds(clean.span)


def test_codex_log_without_session_meta_remains_identifiable_but_has_no_uid(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'orphan.jsonl', CODEX[1:])

  session = SessionHandler.parse(path)

  assert isinstance(session, Session)
  assert (session.type, session.uid) == ('cx', None)


def _first_and_second(tmp_path: Path) -> tuple[Path, Path, float, float]:
  first = tmp_path / 'first.txt'
  second = tmp_path / 'nested' / 'second.txt'
  first.write_text('one', encoding='utf-8')
  second.parent.mkdir()
  second.write_text('two', encoding='utf-8')
  first_time = datetime(2026, 8, 1, 12, tzinfo=timezone.utc).timestamp()
  second_time = datetime(2026, 9, 1, 12, tzinfo=timezone.utc).timestamp()
  os.utime(first, (first_time, first_time))
  os.utime(second, (second_time, second_time))
  return first, second, first_time, second_time


def test_file_records_have_their_modified_time(tmp_path: Path) -> None:
  first, second, first_time, second_time = _first_and_second(tmp_path)

  assert probe(first).updated.timestamp() == first_time
  assert probe(second).updated.timestamp() == second_time


def test_a_folder_counts_and_spans_what_it_directly_holds(tmp_path: Path) -> None:
  _first_and_second(tmp_path)

  folder = FolderHandler.parse(tmp_path)

  assert _iso(folder.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-01T12:00:00+00:00',
    '2026-08-01T12:00:00+00:00',
  ]]
  assert (folder.data['files'], folder.data['folders'], folder.data['bytes']) == (1, 1, 3)


def test_a_folder_counts_nothing_ignored(tmp_path: Path) -> None:
  (tmp_path / 'kept.txt').write_text('kept', encoding='utf-8')
  for name in ('scratch.tmp', 'Thumbs.db', '~$doc.docx'):
    (tmp_path / name).write_text('ignored', encoding='utf-8')
  (tmp_path / '.git').mkdir()

  folder = FolderHandler.parse(tmp_path)

  assert (folder.data['files'], folder.data['folders'], folder.data['bytes']) == (1, 0, 4)


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

  session = SessionHandler.parse(path)

  assert _iso(session.span) == [datetime.fromisoformat(value) for value in ['2026-08-20T01:01:00+00:00', '2026-08-20T01:03:00+00:00']]


def test_session_topic_skips_the_injected_agents_preamble(tmp_path: Path) -> None:
  preamble = {
    **CODEX[2],
    'payload': {
      **CODEX[2]['payload'],
      'content': [{'type': 'input_text', 'text': '# AGENTS.md instructions for D:\\_\n\n<INSTRUCTIONS>\nrules\n</INSTRUCTIONS>'}],
    },
  }
  path = _jsonl(tmp_path / 'codex.jsonl', [CODEX[0], CODEX[1], preamble, CODEX[2], CODEX[3]])

  session = SessionHandler.parse(path)

  assert session.data['topic'] == 'Question'


def test_placeholder_and_future_times_are_not_times(tmp_path: Path) -> None:
  android = datetime(1981, 1, 1, 1, 1, 2).astimezone()
  assert Handler.valid_time(android) is None
  assert Handler.valid_time(datetime(1980, 1, 1).astimezone()) is None
  assert Handler.valid_time(datetime(1970, 1, 1, tzinfo=timezone.utc)) is None
  assert Handler.valid_time(datetime.now(timezone.utc) + timedelta(days=2)) is None
  real = datetime(1994, 10, 7, 3, 0, 54, tzinfo=timezone.utc)
  assert Handler.valid_time(real) == real

  assert Handler.time(datetime(1981, 1, 1, 1, 1, 2)) is None
  assert Handler.time((datetime.now(timezone.utc) + timedelta(days=2)).isoformat()) is None
  assert Handler.time(real.isoformat()) == real

  stale = tmp_path / 'zero.txt'
  stale.write_text('x', encoding='utf-8')
  os.utime(stale, (0, 0))
  assert FolderHandler.parse(tmp_path).span is None


def test_a_file_stamped_at_epoch_zero_has_no_modified_time(tmp_path: Path) -> None:
  stale = tmp_path / 'zero.txt'
  stale.write_text('x', encoding='utf-8')
  os.utime(stale, (0, 0))

  assert probe(stale).updated is None


PONG = 'Reply with exactly PONG'
REMINDER = '<system-reminder>context</system-reminder>'
ENVELOPE = 'Page: stuff\n\n## My request for Codex:\nSummarize the page'
GENERATED = 'A command failed. Diagnose the error and fix it.'


def _human_session(tmp_path: Path) -> Path:
  pong = {**CLAUDE[0], 'uuid': 'probe', 'message': {'role': 'user', 'content': PONG}}
  reminder = {**CLAUDE[0], 'uuid': 'reminder', 'message': {'role': 'user', 'content': REMINDER}}
  envelope = {**CLAUDE[0], 'uuid': 'envelope', 'message': {'role': 'user', 'content': ENVELOPE}}
  return _jsonl(tmp_path / 'claude.jsonl', [pong, reminder, envelope, CLAUDE[1]])


def test_human_messages_leave_out_generated_text_and_envelopes(tmp_path: Path) -> None:
  session = SessionHandler.parse(_human_session(tmp_path))
  turns = (*(SessionTurn('user', text, None) for text in (PONG, REMINDER, ENVELOPE)), SessionTurn('assistant', 'Answer', None))

  assert isinstance(session, Session)
  assert session.data['turns'] == 4
  assert session.data['normalized_name'].endswith(' - Summarize the page.claude-one.jsonl')
  assert SessionHandler.human_messages(turns) == ('Summarize the page',)
  assert SessionHandler.typed('/clear') == ''
  assert SessionHandler.typed('<realtime_delegation><input>Fix the light</input></realtime_delegation>') == 'Fix the light'


def test_a_claude_code_topic_keeps_generated_text(tmp_path: Path) -> None:
  # Linked Data's topic is the first prompt as written; leaving out generated text and envelopes is normalized_name's.
  session = SessionHandler.parse(_human_session(tmp_path))

  assert session.data['topic'] == PONG


def test_session_of_generated_text_only_has_no_topic_in_its_name(tmp_path: Path) -> None:
  generated = {**CLAUDE[0], 'message': {'role': 'user', 'content': GENERATED}}
  session = SessionHandler.parse(_jsonl(tmp_path / 'claude.jsonl', [generated, CLAUDE[1]]))

  assert SessionHandler.human_messages((SessionTurn('user', GENERATED, None),)) == ()
  assert ' - ' not in session.data['normalized_name']


def test_a_session_of_generated_text_only_has_it_as_its_topic(tmp_path: Path) -> None:
  generated = {**CLAUDE[0], 'message': {'role': 'user', 'content': GENERATED}}
  session = SessionHandler.parse(_jsonl(tmp_path / 'claude.jsonl', [generated, CLAUDE[1]]))

  assert session.data['topic'] == GENERATED


@pytest.mark.parametrize('junction', [False, True])
@pytest.mark.parametrize('dangling', [False, True])
def test_links_keep_their_physical_name_and_target_without_descent(tmp_path: Path, junction: bool, dangling: bool) -> None:
  root, target = tmp_path / 'listing', tmp_path / 'different-target-name'
  root.mkdir()
  link = root / 'link-name'
  (root / 'ordinary.txt').write_text('ordinary', encoding='utf-8')
  target.mkdir()
  (target / 'target-only.txt').write_text('not below the link', encoding='utf-8')
  if junction:
    if os.name != 'nt':
      pytest.skip('a junction is a Windows link')
    import _winapi
    _winapi.CreateJunction(str(target), str(link))
  else:
    try:
      link.symlink_to(target, target_is_directory=True)
    except OSError as error:
      pytest.skip(f'this host creates no symbolic link: {error}')
  if dangling:
    shutil.rmtree(target)

  record = probe(link)
  folder = FolderHandler.parse(root)

  assert (record.type, record.name) == ('junction' if junction else 'symlink', 'link-name')
  assert Path(record.data['target']).name == 'different-target-name'
  assert record.type not in HANDLERS
  assert (folder.data['files'], folder.data['folders'], folder.data['bytes']) == (1, 0, len('ordinary'))


def test_a_hermes_log_on_its_own_is_identified_from_its_content(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / '2026-05-12_main_20260512_035400_c197642b.jsonl', HERMES)

  assert probe(path).type == 'session'
  session = SessionHandler.parse(path)
  assert (session.type, session.uid) == ('hermes', '20260512_035400_c197642b')
  assert (session.data['turns'], session.name) == (2, 'Question')
  assert _iso(session.span) == [datetime.fromisoformat(value) for value in ['2026-05-12T10:54:00+00:00', '2026-05-12T10:55:00+00:00']]


def test_an_agy_transcript_and_its_session_folder_are_identified(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'brain' / AGY_UID / '.system_generated' / 'logs' / 'transcript_full.jsonl', AGY)

  session = SessionHandler.parse(path)

  assert (session.type, session.uid) == ('agy', AGY_UID)
  assert (session.data['turns'], session.name) == (2, 'Question')
  assert _iso(session.span) == [datetime.fromisoformat(value) for value in ['2026-08-29T14:35:31+00:00', '2026-08-29T14:49:31+00:00']]

  folder = SessionFolderHandler.parse(path.parents[2])
  assert folder.status == 'parsed'
  assert (folder.data['harness'], folder.data['uid'], folder.data['sessions']) == ('agy', AGY_UID, 1)


def test_an_agy_session_folder_is_probed_by_its_path(tmp_path: Path) -> None:
  brain = tmp_path / '.gemini' / 'antigravity-cli' / 'brain'
  path = _jsonl(brain / AGY_UID / '.system_generated' / 'logs' / 'transcript_full.jsonl', AGY)

  assert probe(path.parents[2]).type == 'sessionfolder'


def test_an_agy_session_folder_is_told_by_its_path(tmp_path: Path) -> None:
  outside = _jsonl(tmp_path / 'brain' / AGY_UID / '.system_generated' / 'logs' / 'transcript_full.jsonl', AGY)
  inside = _jsonl(tmp_path / '.gemini' / 'antigravity-cli' / 'brain' / AGY_UID / '.system_generated' / 'logs' / 'transcript_full.jsonl', AGY)

  assert probe(outside.parents[2]).type == 'folder'
  assert probe(inside.parents[2]).type == 'sessionfolder'


def test_a_filesystem_root_is_never_ignored(tmp_path: Path) -> None:
  root = Path(tmp_path.anchor)

  assert probe(root).type == 'folder'


def test_a_dot_folder_is_walked_and_venv_and_git_are_not(tmp_path: Path) -> None:
  """Alex, 2026-09-17 03:51: "all files can be potentially indexd., It is critical that secrets are
  indexed. I have lost lots of secrets because of ignored dot files" and "venv, .git are ignored".
  So the dot prefix is not a rule and the hidden attribute is not a rule; the named list is."""

  store = tmp_path / '.claude' / 'projects'
  store.mkdir(parents=True)
  (store / 'session.jsonl').write_text('{}', encoding='utf-8')
  secrets = tmp_path / '.ssh'
  secrets.mkdir()
  (secrets / 'id_ed25519').write_text('key', encoding='utf-8')
  if os.name == 'nt':
    subprocess.run(['attrib', '+H', str(secrets)], check=True)
  for name in ('.git', 'venv', '.venv'):
    folder = tmp_path / name
    folder.mkdir()
    (folder / 'inside.txt').write_text('inside', encoding='utf-8')

  assert probe(tmp_path / '.claude').type == 'folder'
  assert probe(store).type == 'folder'
  assert probe(store / 'session.jsonl').type == 'session'
  assert probe(secrets).type == 'folder'
  assert probe(secrets / 'id_ed25519').type == 'file'
  for name in ('.git', 'venv', '.venv'):
    assert probe(tmp_path / name).type == 'ignored'
  assert 'ignored' not in HANDLERS


def test_a_gemini_cli_chat_is_read_as_itself(tmp_path: Path) -> None:
  """Its header carries a sessionId, which is the whole Claude Code test, so without a reader of its
  own it is read as Claude Code: no turns, and every chat of one service under the service's id."""

  def chat(name: str, started: str, said: str) -> Path:
    path = tmp_path / name
    path.write_text('\n'.join(json.dumps(row) for row in (
      {'sessionId': 'a2a-server', 'projectHash': 'abc123', 'startTime': started,
       'lastUpdated': started, 'kind': 'main'},
      {'$set': {'messages': [{'id': 'm1', 'timestamp': started, 'type': 'user',
                              'content': [{'text': said}]}]}},
    )), encoding='utf-8')
    return path

  first = chat('session-2026-08-24T13-51-a2a-serv.jsonl', '2026-08-24T13:51:09.797Z', 'first')
  second = chat('session-2026-08-24T13-52-a2a-serv.jsonl', '2026-08-24T13:52:06.188Z', 'second')

  readings = [SessionHandler.parse(path) for path in (first, second)]
  assert [one.type for one in readings] == ['gemini', 'gemini']
  assert readings[0].uid != readings[1].uid, 'one service id must not fold two chats into one'
  assert readings[0].uid == 'a2a-server/2026-08-24T13:51:09.797Z'
  assert [one.data['turns'] for one in readings] == [1, 1]
  assert readings[0].name == 'first'
  assert all(one.span is not None for one in readings)


def test_a_sqlite_file_is_read_as_material(tmp_path: Path) -> None:
  """Alex's rule for an old location index: it is discovered material, read like a .rar file and
  never written, read once via handler and never reopened. So an index standing beside files now
  sealed in an archive is still known: what it indexed and what it recorded, without opening it."""
  database = tmp_path / 'old-index.sqlite'
  connection = sqlite3.connect(database)
  with connection:
    connection.execute('CREATE TABLE records (uid TEXT PRIMARY KEY, path TEXT, size INTEGER)')
    connection.execute('CREATE TABLE spans (uid TEXT, first TEXT, last TEXT)')
    connection.execute("INSERT INTO records VALUES ('a', 'x.md', 10)")
  connection.close()
  (tmp_path / 'note.md').write_text('not a database', encoding='utf-8')

  assert HANDLERS[probe(database).type] is SqliteHandler
  assert probe(tmp_path / 'note.md').type != 'sqlite'

  read = SqliteHandler.parse(database)
  assert list(read.data['tables']) == ['records', 'spans']
  assert read.data['tables']['records'] == ['uid', 'path', 'size']
  assert read.meta['size'] == database.stat().st_size
  # Opened immutable, so SQLite writes neither companion beside a file in a synced folder.
  assert sorted(path.name for path in tmp_path.iterdir()) == ['note.md', 'old-index.sqlite']


def test_ten_digits_that_are_not_a_time_do_not_stop_a_walk(tmp_path: Path) -> None:
  """A ten-digit number in a name is as likely to be an account number as a timestamp."""
  for name in ('order 9999999999.pdf', 'statement 1600000000.pdf', 'acct 4111111111.csv'):
    (tmp_path / name).write_text('x', encoding='utf-8')

  assert FolderHandler.parse(tmp_path).data['files'] == 3
  assert Handler.named('order 9999999999.pdf') is None, 'a year-2286 number is not a time'
  assert Handler.named('statement 1600000000.pdf') is not None, 'a real epoch still reads'


def test_a_name_spelling_a_date_this_host_cannot_place_does_not_stop_a_walk(tmp_path: Path) -> None:
  """A far date in a name is a number shaped like a date; a hierarchy walk does not stop for it."""
  for name in ('scan 2999-12-31.jpg', 'scan 9999-12-31.jpg', 'note 2024-03-05.md'):
    (tmp_path / name).write_text('x', encoding='utf-8')

  assert FolderHandler.parse(tmp_path).data['files'] == 3
  assert Handler.named('scan 9999-12-31.jpg') is None
  assert Handler.named('note 2024-03-05.md') is not None, 'a real date still reads'


def test_parse_messages_reads_claude_code_messages() -> None:
  session, messages = SessionHandler.parse_messages('cc', CLAUDE)

  assert {key: session[key] for key in ('uid', 'parent_uid', 'topic', 'name', 'models')} == {
    'uid': 'claude-one', 'parent_uid': None, 'topic': 'Question', 'name': 'Question', 'models': {'claude-opus-5'},
  }
  assert session['times'] == [datetime.fromisoformat(value) for value in ['2026-08-20T02:00:00+00:00', '2026-08-20T02:01:00+00:00']]
  assert all(isinstance(message, Record) for message in messages)
  assert [(message.type, message.name, message.meta) for message in messages] == [
    ('user', 'Question', {'uid': 'one', 'line': 1}),
    ('agent', 'Answer', {'uid': 'two', 'line': 2}),
  ]
  assert (messages[0].ts, messages[0].data) == (datetime.fromisoformat('2026-08-20T02:00:00+00:00'), CLAUDE[0])


def test_parse_messages_reads_a_prompt_sent_while_the_session_worked() -> None:
  """Claude Code keeps a prompt the person sends mid-turn as a queued_command attachment marked human: it is a user message."""
  sent = {'type': 'attachment', 'uuid': 'three', 'sessionId': 'claude-one', 'timestamp': '2026-08-20T02:02:00Z',
          'attachment': {'type': 'queued_command', 'prompt': 'And the epics too', 'origin': {'kind': 'human'}, 'humanTurn': True}}
  other = {'type': 'attachment', 'uuid': 'four', 'sessionId': 'claude-one', 'timestamp': '2026-08-20T02:03:00Z',
           'attachment': {'type': 'queued_command', 'prompt': '<task-notification>done</task-notification>', 'origin': {'kind': 'task-notification'}}}

  session, messages = SessionHandler.parse_messages('cc', CLAUDE + [sent, other])

  assert [(message.type, message.name, message.meta) for message in messages[2:]] == [
    ('user', 'And the epics too', {'uid': 'three', 'line': 3}),
    ('attachment', 'attachment', {'uid': 'four', 'line': 4}),
  ]
  assert session['topic'] == 'Question', 'the first prompt stays the topic'


def test_parse_messages_reads_a_prompt_sent_while_the_session_worked_as_blocks() -> None:
  """A prompt sent mid-turn with an image is its blocks: its text is the text blocks'."""
  sent = {'type': 'attachment', 'uuid': 'three', 'sessionId': 'claude-one', 'timestamp': '2026-08-20T02:02:00Z',
          'attachment': {'type': 'queued_command', 'origin': {'kind': 'human'}, 'humanTurn': True,
                         'prompt': [{'type': 'text', 'text': 'Look at this'}, {'type': 'image', 'source': {'type': 'base64', 'data': ''}}]}}

  _, messages = SessionHandler.parse_messages('cc', CLAUDE + [sent])

  assert (messages[2].type, messages[2].name) == ('user', 'Look at this')


def test_parse_messages_reads_codex_messages() -> None:
  session, messages = SessionHandler.parse_messages('cx', CODEX)

  assert (session['uid'], session['topic'], session['name']) == ('codex-one', 'Question', 'Question')
  assert [message.type for message in messages] == ['session_meta', 'turn_context', 'user', 'agent']
  assert [message.meta['line'] for message in messages] == [1, 2, 3, 4]
  assert all(UUID(message.meta['uid']) for message in messages)


def test_parse_messages_numbers_messages_after_an_offset() -> None:
  _, whole = SessionHandler.parse_messages('cx', CODEX)

  session, messages = SessionHandler.parse_messages('cx', CODEX[2:], offset=2, uid='codex-one')

  assert session['uid'] == 'codex-one'
  assert [(message.type, message.meta) for message in messages] == [(message.type, message.meta) for message in whole[2:]]


def test_parse_messages_drops_the_nul_postgres_cannot_hold() -> None:
  line = {**CLAUDE[0], 'toolUseResult': {'stdout': 'SQLite format 3\x00', 'lines': ['w\x00s\x00l']}}

  _, [message] = SessionHandler.parse_messages('cc', [line])

  assert message.data['toolUseResult'] == {'stdout': 'SQLite format 3', 'lines': ['wsl']}
  assert '\\u0000' not in json.dumps(message.data)


def test_parse_messages_reads_only_claude_code_and_codex() -> None:
  with pytest.raises(NotImplementedError):
    SessionHandler.parse_messages('hermes', HERMES)


def _chatgpt(uid: str, question: str = 'Question') -> dict:
  return {
    'id': uid, 'title': question, 'create_time': 1785585600, 'update_time': 1785585720,
    'current_node': 'answer', 'default_model_slug': 'gpt-5.6',
    'mapping': {
      'root': {'id': 'root', 'parent': None, 'message': None},
      'question': {'id': 'question', 'parent': 'root', 'message': {
        'author': {'role': 'user'}, 'create_time': 1785585660, 'content': {'content_type': 'text', 'parts': [question]}}},
      'answer': {'id': 'answer', 'parent': 'question', 'message': {
        'author': {'role': 'assistant'}, 'create_time': 1785585720, 'content': {'content_type': 'text', 'parts': ['Answer']},
        'metadata': {'model_slug': 'gpt-5.6'}}},
      'branch': {'id': 'branch', 'parent': 'question', 'message': {
        'author': {'role': 'assistant'}, 'create_time': 1785585700, 'content': {'content_type': 'text', 'parts': ['Not on the chain']}}},
    },
  }


def _claude(uid: str) -> dict:
  return {
    'uuid': uid, 'name': 'Question', 'created_at': '2026-08-01T12:00:00Z', 'updated_at': '2026-08-01T12:02:00Z',
    'chat_messages': [
      {'sender': 'human', 'created_at': '2026-08-01T12:01:00Z',
       'content': [{'type': 'text', 'text': 'Question'}, {'type': 'tool_use', 'name': 'ignored'}]},
      {'sender': 'assistant', 'created_at': '2026-08-01T12:02:00Z', 'content': [{'type': 'text', 'text': 'Answer'}]},
    ],
  }


def test_probe_tells_an_export_by_its_name(tmp_path: Path) -> None:
  for name in ('conversations.json', 'conversations-000.json', 'other.json'):
    (tmp_path / name).write_text('[]', encoding='utf-8')
  assert [probe(tmp_path / name).type for name in ('conversations.json', 'conversations-000.json', 'other.json')] == \
    ['export', 'export', 'file']
  assert HANDLERS['export'] is handlers_module.ExportHandler


def test_a_chatgpt_export_is_its_conversations_along_their_chains(tmp_path: Path) -> None:
  path = tmp_path / 'conversations-000.json'
  path.write_text(json.dumps([_chatgpt('one'), _chatgpt('two', 'Second')]), encoding='utf-8')

  record = handlers_module.ExportHandler.parse(path)
  first, second = handlers_module.ExportHandler.sessions(path)

  assert (record.type, record.data['harness'], record.data['sessions']) == ('export', 'chatgpt', 2)
  assert (record.span.start, record.span.end) == (datetime.fromtimestamp(1785585600).astimezone(), datetime.fromtimestamp(1785585720).astimezone())
  assert isinstance(first, Session) and (first.type, first.uid, first.name) == ('chatgpt', 'one', 'Question')
  assert (first.data['turns'], first.data['topic'], first.data['models']) == (2, 'Question', ['gpt-5.6'])
  assert first.created == datetime.fromtimestamp(1785585600).astimezone()
  assert first.data['normalized_name'].endswith(' 2~2m - Question.one.json')
  assert second.name == 'Second'


def test_an_anthropic_export_is_read_by_its_conversations_not_by_what_is_beside_it(tmp_path: Path) -> None:
  (tmp_path / 'chat.html').write_text('<html></html>', encoding='utf-8')
  path = tmp_path / 'conversations.json'
  path.write_text(json.dumps([_claude('c-one')]), encoding='utf-8')

  session, = handlers_module.ExportHandler.sessions(path)

  assert handlers_module.ExportHandler.parse(path).data == {'harness': 'claude', 'sessions': 1}
  assert (session.type, session.uid, session.name, session.data['turns']) == ('claude', 'c-one', 'Question', 2)
  assert (session.span.start, session.span.end) == (datetime(2026, 8, 1, 12, tzinfo=timezone.utc), datetime(2026, 8, 1, 12, 2, tzinfo=timezone.utc))


def test_an_export_of_anything_else_raises(tmp_path: Path) -> None:
  path = tmp_path / 'conversations.json'
  for body in ([{'id': 'x'}], [_chatgpt('one'), _claude('two')], {'conversations': []}, []):
    path.write_text(json.dumps(body), encoding='utf-8')
    with pytest.raises(ValueError):
      handlers_module.ExportHandler.parse(path)


def test_gppufs_reads_an_export_inside_a_zip(tmp_path: Path) -> None:
  import zipfile
  from gppu.fs.gppufs import GppuFileSystem
  with zipfile.ZipFile(tmp_path / 'chatgpt.zip', 'w') as archive:
    archive.writestr('conversations.json', json.dumps([_chatgpt('one')]))
    archive.writestr('chat.html', '<html></html>')
  fs = GppuFileSystem(tmp_path)
  assert fs.info('chatgpt.zip/conversations.json')['gppu']['handlers'] == ['export']
  assert fs.info('chatgpt.zip/conversations.json', refresh=True)['gppu']['record']['data'] == {'harness': 'chatgpt', 'sessions': 1}
