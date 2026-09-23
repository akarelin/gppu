from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

import pytest
import gppu.handlers as handlers_module
from gppu import OSType, TimeSpan, detect_os

from gppu.handlers import (
  typed,
  ArchiveHandler,
  BrowserHandler,
  ChatGPTHandler,
  AnthropicHandler,
  CSVFile,
  CSVHandler,
  EmailFile,
  EmailHandler,
  FileHandler,
  FolderHandler,
  GitRepository,
  GitHandler,
  Handler,
  HandlerError,
  ImageHandler,
  IgnoredHandler,
  LogFile,
  LogHandler,
  MarkdownFile,
  MarkdownHandler,
  SessionHandler,
  VideoHandler,
  valid_time,
  FileStats,
  Record,
  SessionFile,
  SessionFolder,
)


class CompleteFileHandler(
  FileHandler,
  IgnoredHandler,
  ChatGPTHandler,
  AnthropicHandler,
  MarkdownHandler,
  CSVHandler,
  LogHandler,
  EmailHandler,
  SessionHandler,
  ArchiveHandler,
  GitHandler,
  FolderHandler,
):
  """The handler composition exercised by this consumer test module."""


archive_handler = ArchiveHandler()
chatgpt_handler = ChatGPTHandler()
anthropic_handler = AnthropicHandler()
csv_handler = CSVHandler()
file_handler = CompleteFileHandler()
folder_handler = FolderHandler()
git_handler = GitHandler()
log_handler = LogHandler()
email_handler = EmailHandler()
markdown_handler = MarkdownHandler()
session_handler = SessionHandler()

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



def _rar_creator() -> Path | None:
  if executable := shutil.which('rar'):
    return Path(executable)
  if detect_os() == OSType.W11:
    roots = tuple(
      Path(os.environ[name])
      for name in ('ProgramFiles', 'ProgramFiles(x86)')
      if name in os.environ
    )
    for root in roots:
      executable = root / 'WinRAR' / 'Rar.exe'
      if executable.is_file():
        return executable
  return None


RAR = _rar_creator()


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


def _git_commit(path: Path, message: str, timestamp: str) -> None:
  env = {
    **os.environ,
    'GIT_AUTHOR_DATE': timestamp,
    'GIT_COMMITTER_DATE': timestamp,
  }
  subprocess.run(['git', 'add', '.'], cwd=path, check=True, capture_output=True)
  subprocess.run(
    [
      'git',
      '-c', 'user.name=gppu tests',
      '-c', 'user.email=gppu@localhost',
      'commit', '-qm', message,
    ],
    cwd=path,
    env=env,
    check=True,
    capture_output=True,
  )


def _bounds(span) -> tuple[datetime, datetime]:
  assert isinstance(span, TimeSpan)
  return span.start, span.end


def _iso(span) -> list[datetime]:
  return list(_bounds(span))


def _stats(stats):
  return stats.files, stats.folders, stats.bytes, _bounds(stats.span) if stats.span else None


def test_session_handler_returns_stats_and_complete_object(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)

  stats, session = session_handler(path)

  assert isinstance(session, SessionFile)
  assert (session.harness, session.uid) == ('cx', 'codex-one')
  assert (len(session.turns), session.user_messages) == (2, ('Question',))
  assert session.models == ('gpt-5.6',)
  assert (stats.files, stats.sessions, stats.turns) == (1, 1, 2)
  assert _iso(stats.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-20T01:00:00+00:00',
    '2026-08-20T01:02:00+00:00',
  ]]

  record = file_handler.probe(path, recursive=False)[0]
  assert record.handlers == ('session',)
  assert _bounds(record.span) == _bounds(stats.span)


def test_session_identification_checks_extension_and_size_before_reading(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  unsupported = tmp_path / 'rollout.json'
  unsupported.write_text(json.dumps(CODEX[0]), encoding='utf-8')
  empty = tmp_path / 'empty.jsonl'
  empty.touch()
  supported = _jsonl(tmp_path / 'rollout.JSONL', CODEX)
  reads = []
  original = SessionHandler._head

  def counted(path: Path):
    reads.append(path)
    return original(path)

  monkeypatch.setattr(SessionHandler, '_head', staticmethod(counted))

  assert session_handler.identify_sync(unsupported) is False
  assert session_handler.identify_sync(empty) is False
  assert session_handler.identify_sync(supported) is True
  assert reads == [supported]


def test_session_folder_identification_uses_structural_markers_only(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  folder = tmp_path / 'sessions'
  _jsonl(folder / 'nested.jsonl', CODEX)
  reads = []
  original = SessionHandler._head

  def counted(path: Path):
    reads.append(path)
    return original(path)

  monkeypatch.setattr(SessionHandler, '_head', staticmethod(counted))

  assert session_handler.identify_sync(folder) is False
  assert reads == []

  (folder / 'state.db').touch()
  assert session_handler.identify_sync(folder) is True
  assert reads == []


def test_file_identification_reads_each_session_head_once(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  class SessionFileHandler(FileHandler, SessionHandler, FolderHandler):
    pass

  first = _jsonl(tmp_path / 'first.jsonl', CODEX)
  second = _jsonl(tmp_path / 'nested' / 'second.jsonl', CLAUDE)
  reads = []
  original = SessionHandler._head

  def counted(path: Path):
    reads.append(path)
    return original(path)

  monkeypatch.setattr(SessionHandler, '_head', staticmethod(counted))

  SessionFileHandler().identify_sync(tmp_path)

  assert sorted(reads) == sorted((first, second))
  assert len(reads) == 2


def test_openai_export_chunks_are_one_session_collection(tmp_path: Path) -> None:
  path = tmp_path / 'openai.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('conversation_asset_file_names.json', '{}')
    archive.writestr('conversations-000.json', json.dumps([_chatgpt('chatgpt-one')]))
    archive.writestr('conversations-001.json', json.dumps([_chatgpt('chatgpt-two', 'Second')]))

  assert chatgpt_handler.identify(path) is True
  stats, sessions = chatgpt_handler(path)

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
  assert _iso(stats.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-01T12:00:00+00:00',
    '2026-08-01T12:02:00+00:00',
  ]]
  assert file_handler.identify(path, recursive=False)[0].handlers == ('chatgpt', 'archive')


def test_anthropic_export_uses_flat_human_and_assistant_messages(tmp_path: Path) -> None:
  path = tmp_path / 'anthropic.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('projects.json', '[]')
    archive.writestr('conversations.json', json.dumps([_claude('claude-one')]))

  assert anthropic_handler.identify(path) is True
  stats, sessions = anthropic_handler(path)

  assert isinstance(sessions, SessionFolder)
  assert (sessions.harness, stats.sessions, stats.turns) == ('claude', 1, 2)
  assert sessions.files[0].uid == 'claude-one'
  assert sessions.files[0].user_messages == ('Question',)
  assert sessions.files[0].topic == 'Question'
  assert _iso(stats.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-01T12:00:00+00:00',
    '2026-08-01T12:02:00+00:00',
  ]]


def test_chatgpt_and_anthropic_handlers_load_extracted_export_folders(tmp_path: Path) -> None:
  chatgpt = tmp_path / 'chatgpt'
  chatgpt.mkdir()
  chatgpt_json = chatgpt / 'conversations-000.json'
  chatgpt_json.write_text(json.dumps([_chatgpt('chatgpt-folder')]), encoding='utf-8')

  claude = tmp_path / 'claude'
  claude.mkdir()
  claude_json = claude / 'conversations.json'
  claude_json.write_text(json.dumps([_claude('claude-folder')]), encoding='utf-8')

  chatgpt_stats, chatgpt_sessions = chatgpt_handler(chatgpt)
  claude_stats, claude_sessions = anthropic_handler(claude)

  assert chatgpt_handler.identify(chatgpt) is True
  assert anthropic_handler.identify(claude) is True
  assert (chatgpt_stats.files, chatgpt_sessions.files[0].location) == (1, chatgpt_json)
  assert (claude_stats.files, claude_sessions.files[0].location) == (1, claude_json)
  assert file_handler.identify(chatgpt, recursive=False)[0].handlers == ('chatgpt', 'folder')
  assert file_handler.identify(claude, recursive=False)[0].handlers == ('claude', 'folder')


def test_file_handler_uses_concrete_handler_mixins(tmp_path: Path) -> None:
  assert isinstance(chatgpt_handler, ChatGPTHandler)
  assert isinstance(anthropic_handler, AnthropicHandler)
  assert isinstance(markdown_handler, MarkdownHandler)
  assert isinstance(csv_handler, CSVHandler)
  assert isinstance(log_handler, LogHandler)
  assert isinstance(folder_handler, FolderHandler)
  assert ChatGPTHandler in CompleteFileHandler.__mro__
  assert AnthropicHandler in CompleteFileHandler.__mro__
  assert MarkdownHandler in CompleteFileHandler.__mro__
  assert CSVHandler in CompleteFileHandler.__mro__
  assert LogHandler in CompleteFileHandler.__mro__
  assert FolderHandler in CompleteFileHandler.__mro__
  assert file_handler.handler_types == (
    IgnoredHandler,
    ChatGPTHandler,
    AnthropicHandler,
    MarkdownHandler,
    CSVHandler,
    LogHandler,
    EmailHandler,
    SessionHandler,
    ArchiveHandler,
    GitHandler,
    FolderHandler,
  )

  stats, folder = folder_handler(tmp_path)

  assert folder == tmp_path
  assert _stats(stats) == _stats(FileStats(0, 0, 0, None))
  assert file_handler.identify(tmp_path, recursive=False)[0].handlers == ('folder',)


def test_handlers_module_constructs_no_handler_objects() -> None:
  constructed = {
    name: value
    for name, value in vars(handlers_module).items()
    if isinstance(value, Handler)
  }

  assert constructed == {}


def test_handlers_copy_additional_metadata_into_probes(tmp_path: Path) -> None:
  supplied = {'source': 'fixture', 'title': 'Caller title'}
  handler = MarkdownHandler(metadata=supplied)
  files = CompleteFileHandler(metadata=supplied)
  supplied['source'] = 'changed later'
  path = tmp_path / 'document.md'
  path.write_text('---\ntitle: Example\n---\n', encoding='utf-8')

  _, markdown = handler(path)
  probe = files.probe(path, recursive=False)[0].probes[0]

  assert handler.metadata == {'source': 'fixture', 'title': 'Caller title'}
  assert markdown.title == 'Example'
  assert probe.metadata == {'source': 'fixture', 'title': 'Caller title'}
  assert probe.handler == 'markdown'


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

  stats, markdown = markdown_handler(path)

  assert isinstance(markdown, MarkdownFile)
  assert markdown.frontmatter == {
    'name': 'Display name',
    'tags': ['meta', 'handlers'],
    'created': '2026-08-27T19:42',
    'updated': '2026-09-01T05:11',
    'unknown': {'nested': 'value'},
  }
  assert (markdown.title, markdown.name, markdown.tags) == (
    'Display name',
    'Display name',
    ('meta', 'handlers'),
  )
  assert _iso(markdown.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-27T19:42:00-07:00',
    '2026-09-01T05:11:00-07:00',
  ]]
  assert _stats(stats) == _stats(FileStats(1, 0, path.stat().st_size, markdown.span))
  assert file_handler.probe(path, recursive=False)[0].handlers == ('markdown',)


def test_markdown_handler_uses_filename_without_frontmatter(tmp_path: Path) -> None:
  path = tmp_path / 'Plain file.md'
  path.write_text('# Plain file\n', encoding='utf-8')

  _, markdown = markdown_handler(path)

  assert markdown.frontmatter == {}
  assert (markdown.title, markdown.name, markdown.tags, markdown.span) == (
    'Plain file',
    'Plain file',
    (),
    None,
  )


def test_markdown_handler_rejects_invalid_frontmatter_mapping(tmp_path: Path) -> None:
  path = tmp_path / 'invalid.md'
  path.write_text('---\n- not\n- a mapping\n---\n', encoding='utf-8')

  stats, error = markdown_handler(path)

  assert stats is None
  assert isinstance(error, HandlerError)
  assert error.error_type == 'ValueError'
  assert 'frontmatter must be a mapping' in error.message

  with pytest.raises(ValueError, match='frontmatter must be a mapping'):
    MarkdownHandler(strict=True)(path)


def test_csv_handler_reads_header_and_every_row(tmp_path: Path) -> None:
  path = tmp_path / 'table.csv'
  path.write_text('title,tags\nOne,"a,b"\nTwo,c\n', encoding='utf-8')

  stats, table = csv_handler(path)

  assert isinstance(table, CSVFile)
  assert table.header == ('title', 'tags')
  assert table.rows == (('One', 'a,b'), ('Two', 'c'))
  assert _stats(stats) == _stats(FileStats(1, 0, path.stat().st_size, None))
  assert file_handler.probe(path, recursive=False)[0].handlers == ('csv',)


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

  stats, table = BillingCSVHandler()(path)

  assert _iso(table.span) == [datetime.fromisoformat(value) for value in [
    '2026-08-27T19:42:00-07:00',
    '2026-09-01T05:11:00-07:00',
  ]]
  assert _bounds(stats.span) == _bounds(table.span)


def test_log_handler_uses_timestamped_rows_for_span(tmp_path: Path) -> None:
  path = tmp_path / 'service.log'
  path.write_text(
    '[2026-09-04T08:00:00-07:00] started\n'
    'continuation without a timestamp\n'
    '2026-09-04 09:15:30,500 finished\n',
    encoding='utf-8',
  )

  stats, log = log_handler(path)

  assert isinstance(log, LogFile)
  assert log.rows == (
    '[2026-09-04T08:00:00-07:00] started',
    'continuation without a timestamp',
    '2026-09-04 09:15:30,500 finished',
  )
  assert _iso(log.span) == [datetime.fromisoformat(value) for value in [
    '2026-09-04T08:00:00-07:00',
    '2026-09-04T09:15:30.500000-07:00',
  ]]
  assert _stats(stats) == _stats(FileStats(1, 0, path.stat().st_size, log.span))
  assert file_handler.probe(path, recursive=False)[0].handlers == ('log',)


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

  stats, email = email_handler(path)

  assert isinstance(email, EmailFile)
  assert email.subject == subject
  assert email.party == party
  assert email.collision == collision
  assert email.timestamp.isoformat() == timestamp
  assert _bounds(stats.span) == _bounds(email.span)
  assert EmailHandler.parse_message(path) is NotImplemented
  record = file_handler.probe(path, recursive=False)[0]
  assert record.handlers == ('email',)
  assert record.metadata['email']['subject'] == subject


def test_email_handler_accepts_a_filename_without_declared_metadata(
  tmp_path: Path,
) -> None:
  path = tmp_path / 'message.EML'
  path.write_bytes(b'payload')

  stats, email = email_handler(path)

  assert email.metadata == {}
  assert email.span is None
  assert stats.span is None


def test_composed_handler_retains_load_error_and_processes_other_files(
  tmp_path: Path,
) -> None:
  class BrokenHandler(Handler):
    name = 'broken'

    def identify_sync(self, path: Path) -> bool:
      return path.suffix == '.bad'

    def call_sync(self, path: Path):
      raise OSError('unreadable fixture')

  class TreeHandler(FileHandler, BrokenHandler, FolderHandler):
    pass

  broken = tmp_path / 'a.bad'
  other = tmp_path / 'b.txt'
  broken.write_text('bad', encoding='utf-8')
  other.write_text('good', encoding='utf-8')

  records = TreeHandler().probe(tmp_path)
  found = {record.path: record for record in records}

  assert set(found) == {tmp_path, broken, other}
  assert found[tmp_path].stats.files == 2
  assert found[broken].probes[0].obj is None
  assert found[broken].probes[0].error.error_type == 'OSError'
  assert found[broken].errors == (found[broken].probes[0].error,)

  with pytest.raises(OSError, match='unreadable fixture'):
    TreeHandler(strict=True).probe(tmp_path)


def test_ignored_paths_remain_visible_without_folder_descent(tmp_path: Path) -> None:
  class TreeHandler(FileHandler, IgnoredHandler, FolderHandler):
    pass

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

  records = TreeHandler().probe(tmp_path)
  found = {record.path: record for record in records}

  assert set(found) == {
    tmp_path,
    git_folder,
    cache_folder,
    ignored_file,
    retained_file,
  }
  assert found[git_folder].handlers == ('ignored', 'folder')
  assert found[cache_folder].handlers == ('ignored', 'folder')
  assert found[ignored_file].handlers == ('ignored',)
  assert found[git_folder].metadata['ignored']['classification'] == 'Ignored'
  assert found[git_folder].metadata['ignored']['no_descent'] is True
  assert found[ignored_file].metadata['ignored']['no_descent'] is False


def test_walk_generators_report_only_folders_they_enter(
  tmp_path: Path,
) -> None:
  class TreeHandler(FileHandler, IgnoredHandler, FolderHandler):
    pass

  entered_folder = tmp_path / 'entered'
  refused_folder = tmp_path / 'refused'
  ignored_folder = tmp_path / '.git'
  for folder in (entered_folder, refused_folder, ignored_folder):
    folder.mkdir()
    (folder / 'child.txt').write_text(folder.name, encoding='utf-8')
  (tmp_path / 'root.txt').write_text('root', encoding='utf-8')
  handler = TreeHandler()

  sync_entered = []
  sync_done = []

  def sync_enter(record: Record) -> bool:
    sync_entered.append(record.path)
    return record.path != refused_folder

  sync_records = list(
    handler.walk_sync(
      tmp_path,
      enter=sync_enter,
      on_folder_done=lambda record: sync_done.append(record.path),
    )
  )
  sync_paths = [record.path for record in sync_records]

  assert tmp_path not in sync_paths
  assert entered_folder / 'child.txt' in sync_paths
  assert refused_folder / 'child.txt' not in sync_paths
  assert ignored_folder / 'child.txt' not in sync_paths
  assert sync_entered == [entered_folder, refused_folder]
  assert sync_done == [entered_folder]

  direct_entered = []
  direct_done = []
  direct = list(
    handler.walk_sync(
      tmp_path,
      recursive=False,
      enter=lambda record: direct_entered.append(record.path) or True,
      on_folder_done=lambda record: direct_done.append(record.path),
    )
  )

  assert {record.path for record in direct} == {
    entered_folder,
    refused_folder,
    ignored_folder,
    tmp_path / 'root.txt',
  }
  assert direct_entered == []
  assert direct_done == []

  async def collect():
    entered = []
    done = []

    def enter(record: Record) -> bool:
      entered.append(record.path)
      return record.path != refused_folder

    records = [
      record
      async for record in handler.walk(
        tmp_path,
        enter=enter,
        on_folder_done=lambda record: done.append(record.path),
      )
    ]
    return records, entered, done

  async_records, async_entered, async_done = asyncio.run(collect())

  assert [record.path for record in async_records] == sync_paths
  assert async_entered == sync_entered
  assert async_done == sync_done


def test_identify_and_probe_consume_the_public_walk(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  class TreeHandler(FileHandler, FolderHandler):
    pass

  nested = tmp_path / 'nested'
  nested.mkdir()
  (nested / 'one.txt').write_text('one', encoding='utf-8')
  handler = TreeHandler()
  original = handler.walk_sync
  calls = []

  def counted(path, recursive=True, enter=None, on_folder_done=None):
    calls.append(path.path if isinstance(path, Record) else path)
    yield from original(path, recursive, enter, on_folder_done)

  monkeypatch.setattr(handler, 'walk_sync', counted)

  identified = handler.identify_sync(tmp_path)
  identify_calls = len(calls)
  probed = handler.probe_sync(tmp_path)

  assert identify_calls > 0
  assert len(calls) > identify_calls
  assert [record.path for record in probed] == [
    record.path for record in identified
  ]
  assert _stats(probed[0].stats) == _stats(FileStats(1, 1, 3, probed[0].span))


def test_exif_handlers_are_unregistered_placeholders() -> None:
  for handler in (ImageHandler, VideoHandler):
    assert 'identify' not in handler.__dict__
    assert '__call__' not in handler.__dict__
    assert handler not in file_handler.handler_types


def test_named_conversation_export_with_unknown_shape_fails(tmp_path: Path) -> None:
  path = tmp_path / 'unknown.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('conversations.json', json.dumps([{'messages': []}]))

  assert anthropic_handler.identify(path) is True
  stats, error = anthropic_handler(path)

  assert stats is None
  assert isinstance(error, HandlerError)
  assert 'conversation format is not claude' in error.message

  with pytest.raises(ValueError, match='conversation format is not claude'):
    AnthropicHandler(strict=True)(path)


def test_handlers_are_awaitable_without_changing_synchronous_calls(tmp_path: Path) -> None:
  session_path = _jsonl(tmp_path / 'rollout.jsonl', CODEX)
  archive_path = tmp_path / 'files.zip'
  with zipfile.ZipFile(archive_path, 'w') as archive:
    archive.writestr('one.txt', 'one')

  async def exercise() -> None:
    assert await session_handler.identify(session_path) is True
    stats, session = await session_handler(session_path)
    assert (stats.sessions, session.uid) == (1, 'codex-one')
    assert (await file_handler.identify(session_path, recursive=False))[0].handlers == ('session',)
    assert _bounds((await file_handler.probe(session_path, recursive=False))[0].span) == _bounds(stats.span)
    assert (await file_handler.load(session_path)).uid == 'codex-one'
    assert await archive_handler.identify(archive_path) is True
    archive_stats, records = await archive_handler(archive_path)
    assert (archive_stats.files, records[0].name) == (1, 'one.txt')

  asyncio.run(exercise())


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


def test_claude_subagent_is_identified_by_its_agent_id(tmp_path: Path) -> None:
  # A subagent transcript carries its parent's sessionId on every record and its own agentId,
  # which is what the file is named after. Without the agent id every subagent in a session
  # answers with the parent's id and denies being one.
  subagent = [
    {**record, 'agentId': 'a067dda7f881a582d', 'isSidechain': True} for record in CLAUDE
  ]
  path = _jsonl(tmp_path / 'agent-a067dda7f881a582d.jsonl', subagent)

  _, session = session_handler(path)

  assert isinstance(session, SessionFile)
  assert (session.uid, session.parent_uid, session.subagent) == (
    'a067dda7f881a582d', 'claude-one', True
  )

  _, plain = session_handler(_jsonl(tmp_path / 'claude.jsonl', CLAUDE))
  assert (plain.uid, plain.parent_uid, plain.subagent) == ('claude-one', None, False)


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

  assert found[first].span.start.timestamp() == first_time
  assert found[second].span.end.timestamp() == second_time
  assert _iso(found[tmp_path].span) == [datetime.fromisoformat(value) for value in [
    '2026-08-01T12:00:00+00:00',
    '2026-09-01T12:00:00+00:00',
  ]]
  assert _stats(found[tmp_path].stats) == _stats(FileStats(2, 1, 6, found[tmp_path].span))


def test_git_history_spans_tracked_repository_folders_and_files(tmp_path: Path) -> None:
  repository = tmp_path / 'repository'
  nested = repository / 'nested'
  first = nested / 'first.txt'
  second = nested / 'second.txt'
  untracked = nested / 'untracked.txt'
  nested.mkdir(parents=True)
  subprocess.run(['git', 'init', '-q'], cwd=repository, check=True, capture_output=True)

  removed = nested / 'removed.txt'
  removed.write_text('removed later', encoding='utf-8')
  _git_commit(repository, 'removed file', '2026-06-01T11:00:00+00:00')
  removed.unlink()
  first.write_text('first', encoding='utf-8')
  _git_commit(repository, 'first', '2026-07-01T12:00:00+00:00')
  first.write_text('changed', encoding='utf-8')
  second.write_text('second', encoding='utf-8')
  _git_commit(repository, 'second', '2026-08-02T13:00:00+00:00')
  untracked.write_text('untracked', encoding='utf-8')
  branch = subprocess.run(
    ['git', 'branch', '--show-current'],
    cwd=repository,
    check=True,
    capture_output=True,
    text=True,
  ).stdout.strip()
  subprocess.run(
    ['git', 'remote', 'add', 'origin', 'git@github.com:example/repository.git'],
    cwd=repository,
    check=True,
    capture_output=True,
  )
  subprocess.run(
    ['git', 'config', f'branch.{branch}.remote', 'origin'],
    cwd=repository,
    check=True,
    capture_output=True,
  )
  subprocess.run(
    ['git', 'config', f'branch.{branch}.merge', f'refs/heads/{branch}'],
    cwd=repository,
    check=True,
    capture_output=True,
  )

  class GitFileHandler(FileHandler, IgnoredHandler, GitHandler, FolderHandler):
    pass

  handler = GitFileHandler()
  found = {record.path: record for record in handler.probe(repository)}

  assert found[repository].handlers == ('git', 'folder')
  assert found[nested].handlers == ('git', 'folder')
  assert found[first].handlers == ('git',)
  assert found[second].handlers == ('git',)
  assert found[untracked].handlers == ()
  assert _iso(found[repository].span) == [datetime.fromisoformat(value) for value in [
    '2026-06-01T11:00:00+00:00',
    '2026-08-02T13:00:00+00:00',
  ]]
  assert _bounds(found[nested].span) == _bounds(found[repository].span)
  assert _iso(found[first].span) == [datetime.fromisoformat(value) for value in [
    '2026-07-01T12:00:00+00:00',
    '2026-08-02T13:00:00+00:00',
  ]]
  assert _iso(found[second].span) == [datetime.fromisoformat(value) for value in [
    '2026-08-02T13:00:00+00:00',
    '2026-08-02T13:00:00+00:00',
  ]]
  git_repository = git_handler(first)[1]
  assert isinstance(git_repository, GitRepository)
  assert git_repository.metadata_path == repository / '.git'
  assert git_repository.upstream_remote == 'origin'
  assert git_repository.upstream_url == 'git@github.com:example/repository.git'
  assert git_repository.metadata['remotes'] == {
    'origin': 'git@github.com:example/repository.git',
  }
  git_probe = found[repository].probes[0]
  assert git_probe.metadata['upstream_url'] == 'git@github.com:example/repository.git'

  async def exercise() -> None:
    assert await git_handler.identify(first) is True
    stats, metadata = await git_handler(first)
    assert _bounds(stats.span) == _bounds(found[first].span)
    assert metadata.metadata_path == repository / '.git'

  asyncio.run(exercise())

  first.write_text('changed again', encoding='utf-8')
  _git_commit(repository, 'third', '2026-09-03T14:00:00+00:00')
  assert _iso(handler.probe(first, recursive=False)[0].span) == [datetime.fromisoformat(value) for value in [
    '2026-07-01T12:00:00+00:00',
    '2026-09-03T14:00:00+00:00',
  ]]


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
  assert _bounds(archive_record.span) == _bounds(probe.stats.span)
  assert file_handler.children(archive_record) == (found[PurePosixPath('logs')],)
  assert file_handler.children(found[PurePosixPath('logs')]) == (
    found[PurePosixPath('logs/first.txt')],
    found[PurePosixPath('logs/second.txt')],
  )


def test_archive_identification_dispatches_only_after_extension_check(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  calls = []
  monkeypatch.setattr(
    zipfile,
    'is_zipfile',
    lambda path: calls.append('zip') or True,
  )
  monkeypatch.setattr(
    ArchiveHandler,
    '_is_rar',
    classmethod(lambda cls, path: calls.append('rar') or True),
  )
  monkeypatch.setattr(
    ArchiveHandler,
    '_is_tar_gz',
    staticmethod(lambda path: calls.append('tar.gz') or True),
  )

  unsupported = tmp_path / 'archive.bin'
  unsupported.touch()
  assert archive_handler.identify_sync(unsupported) is False
  assert calls == []

  for name, expected in (
    ('archive.ZIP', 'zip'),
    ('archive.RAR', 'rar'),
    ('archive.TAR.GZ', 'tar.gz'),
  ):
    path = tmp_path / name
    path.touch()
    calls.clear()
    assert archive_handler.identify_sync(path) is True
    assert calls == [expected]


@pytest.mark.parametrize('field', ('Modified', 'mtime'))
def test_rar_record_accepts_platform_timestamp_labels(field: str) -> None:
  record = ArchiveHandler._rar_record(
    Path('archive.rar'),
    {
      'Name': 'one.txt',
      'Type': 'File',
      'Size': '3',
      field: '2026-08-20 05:00:00,000000000',
    },
  )

  assert record.modified_at is not None


def test_archive_members_use_ignored_rules_and_prune_descendants(
  tmp_path: Path,
) -> None:
  class ArchiveFileHandler(FileHandler, IgnoredHandler, ArchiveHandler):
    pass

  path = tmp_path / 'ignored.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('.git/config', 'config')
    archive.writestr('.git/objects/object', 'object')
    archive.writestr('Thumbs.db', 'thumbnail')
    archive.writestr('retained.txt', 'retained')

  record = ArchiveFileHandler().probe(path, recursive=False)[0]
  records = record.probes[0].obj
  found = {member.path: member for member in records}

  assert set(found) == {
    PurePosixPath('.git'),
    PurePosixPath('Thumbs.db'),
    PurePosixPath('retained.txt'),
  }
  assert found[PurePosixPath('.git')].handlers == ('ignored',)
  assert found[PurePosixPath('.git')].metadata['ignored']['no_descent'] is True
  assert found[PurePosixPath('Thumbs.db')].handlers == ('ignored',)


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


def test_archive_path_requests_only_the_aggregate_root(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  class TreeHandler(FileHandler, FolderHandler):
    pass

  source = tmp_path / 'source'
  source.mkdir()
  (source / 'one.txt').write_text('one', encoding='utf-8')
  handler = TreeHandler()
  original = handler._probe_hierarchy
  retained = []

  def capture(path, recursive, *, retain_records):
    retained.append(retain_records)
    return original(path, recursive, retain_records=retain_records)

  monkeypatch.setattr(handler, '_probe_hierarchy', capture)
  monkeypatch.setattr(
    handler,
    'probe_sync',
    lambda *args, **kwargs: pytest.fail('archive_path_sync called probe_sync'),
  )

  path = handler.archive_path_sync(
    source,
    tmp_path / 'archives',
    'files',
    'zip',
    ZoneInfo('America/Los_Angeles'),
  )

  assert path.suffix == '.zip'
  assert retained == [False]


@pytest.mark.skipif(RAR is None, reason='RARLAB rar is not installed')
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

  assert _stats(probe.stats) == _stats(FileStats(1, 0, source.stat().st_size, probe.stats.span))
  assert probe.stats.span.start.astimezone(timezone.utc).date().isoformat() == '2026-08-20'


def test_rar_reader_finds_the_platform_command_from_path(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  executable = tmp_path / ('unrar.exe' if detect_os() == OSType.W11 else 'unrar')
  executable.touch()
  monkeypatch.setattr(
    shutil,
    'which',
    lambda command: str(executable) if command == 'unrar' else None,
  )

  assert ArchiveHandler.rar_executable() == executable.resolve()


def test_probe_cache_is_invalidated_when_a_file_changes(tmp_path: Path) -> None:
  class CountingHandler(Handler):
    name = 'counting'

    def __init__(self, metadata=None, *, strict: bool = False) -> None:
      super().__init__(metadata, strict=strict)
      self.calls = 0

    def identify_sync(self, path: Path) -> bool:
      return path.suffix == '.count'

    def call_sync(self, path: Path):
      self.calls += 1
      stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
      return FileStats(1, 0, path.stat().st_size, (stamp, stamp)), path.read_text()

  class CountingFileHandler(FileHandler, CountingHandler):
    pass

  handler = CountingFileHandler()
  path = tmp_path / 'one.count'
  path.write_text('one', encoding='utf-8')

  assert handler.probe(path, recursive=False)[0].probes[0].obj == 'one'
  assert handler.probe(path, recursive=False)[0].probes[0].obj == 'one'
  assert handler.calls == 1

  path.write_text('changed', encoding='utf-8')

  assert handler.probe(path, recursive=False)[0].probes[0].obj == 'changed'
  assert handler.calls == 2


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

  assert _iso(session.span) == [datetime.fromisoformat(value) for value in ['2026-08-20T01:00:00+00:00', '2026-08-20T01:03:00+00:00']]


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
  assert _iso(file_handler.probe(archive)[0].probes[0].stats.span) == [datetime.fromisoformat(value) for value in [
    datetime(2026, 8, 20, 1, 0, 0).astimezone().isoformat(),
    datetime(2026, 8, 20, 1, 0, 0).astimezone().isoformat(),
  ]]


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

  archive = tmp_path / 'app.zip'
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


def test_a_folder_that_will_not_be_listed_is_retained_as_an_error(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  closed = tmp_path / 'closed'
  closed.mkdir()
  readable = tmp_path / 'readable.txt'
  readable.write_text('readable', encoding='utf-8')
  original = Path.iterdir

  def denied(self: Path):
    if self == closed:
      raise PermissionError(5, 'Access is denied')
    return original(self)

  monkeypatch.setattr(Path, 'iterdir', denied)
  assert session_handler.identify(closed) is False
  records = file_handler.probe(tmp_path)
  found = {record.path: record for record in records}

  assert readable in found
  assert found[closed].errors[0].operation == 'list'
  assert found[closed].errors[0].error_type == 'PermissionError'


def test_a_child_gone_between_the_listing_and_the_reading_is_not_a_child(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
  (tmp_path / 'here.txt').write_text('here', encoding='utf-8')
  (tmp_path / 'gone.txt').write_text('gone by the time it is read', encoding='utf-8')
  class SessionFileHandler(FileHandler, SessionHandler, FolderHandler):
    pass

  handler = SessionFileHandler()
  original = FileHandler.record

  def vanishing(self: FileHandler, path: Path) -> Record:
    if path.name == 'gone.txt':
      raise FileNotFoundError(2, 'The system cannot find the file specified', str(path))
    return original(self, path)

  monkeypatch.setattr(FileHandler, 'record', vanishing)
  assert [child.name for child in handler.children(tmp_path)] == ['here.txt']


@pytest.mark.parametrize('junction', [False, True])
@pytest.mark.parametrize('dangling', [False, True])
def test_links_keep_their_physical_name_and_target_without_descent(tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch,
                                                                 junction: bool, dangling: bool) -> None:
  root, target = tmp_path / 'listing', tmp_path / 'different-target-name'
  root.mkdir()
  link = root / 'link-name'
  link.touch()
  (root / 'ordinary.txt').write_text('ordinary', encoding='utf-8')
  if not dangling:
    target.mkdir()
    (target / 'target-only.txt').write_text('not below the link', encoding='utf-8')
  original = FileHandler.record
  monkeypatch.setattr(Path, 'is_symlink', lambda path: path == link and not junction)
  monkeypatch.setattr(Path, 'is_junction', lambda path: path == link and junction)
  monkeypatch.setattr(os, 'readlink', lambda path: str(target))
  monkeypatch.setattr(FileHandler, 'record', lambda self, path: original(self, target if path == link else path))

  class Files(FileHandler, FolderHandler):
    pass

  files = Files()
  children = {row.name: row for row in files.children(root)}
  record = children['link-name']
  assert record.path == link
  assert record.target == target
  assert record.metadata['target'] == str(target)
  assert bool(record.errors) == dangling
  assert files.children(record) == files.children(link) == ()
  for records in (files.identify_sync(root), files.probe_sync(root)):
    found = {row.path: row for row in records}
    assert set(found) == {root, link, root / 'ordinary.txt'}
    assert found[link].target == target
    assert bool(found[link].errors) == dangling


@pytest.mark.parametrize('operation', ['readlink', 'stat'])
def test_an_inaccessible_link_remains_visible_when_identified_and_probed(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch,
                                                                      operation: str) -> None:
  link = tmp_path / 'unreadable-link'
  link.touch()
  original = handlers_module.full_path
  monkeypatch.setattr(Path, 'is_symlink', lambda path: path == link)
  monkeypatch.setattr(Path, 'is_junction', lambda path: False)

  def denied(path):
    raise PermissionError('link target access denied')

  monkeypatch.setattr(os, 'readlink', denied if operation == 'readlink' else lambda path: str(tmp_path / 'target'))
  if operation == 'stat':
    monkeypatch.setattr(handlers_module, 'full_path', lambda path: denied(path) if path == link else original(path))
  files = FileHandler()
  for records in (files.identify_sync(tmp_path), files.probe_sync(tmp_path)):
    record = next(row for row in records if row.path == link)
    assert record.name == 'unreadable-link'
    assert [(error.operation, error.error_type) for error in record.errors] == [(operation, 'PermissionError')]
    assert files.children(record) == ()


def test_a_hermes_log_on_its_own_is_identified_from_its_content(tmp_path: Path) -> None:
  path = _jsonl(tmp_path / '2026-05-12_main_20260512_035400_c197642b.jsonl', HERMES)

  assert session_handler.identify(path) is True
  stats, session = session_handler(path)
  assert (session.harness, session.uid) == ('hermes', '20260512_035400_c197642b')
  assert (len(session.turns), session.user_messages) == (2, ('Question',))
  assert _iso(stats.span) == [datetime.fromisoformat(value) for value in ['2026-05-12T10:54:00+00:00', '2026-05-12T10:55:00+00:00']]


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
  assert _iso(stats.span) == [datetime.fromisoformat(value) for value in ['2026-08-29T14:35:31+00:00', '2026-08-29T14:49:31+00:00']]

  folder_stats, folder = session_handler(path.parents[2])
  assert isinstance(folder, SessionFolder)
  assert (folder.harness, folder.uid) == ('agy', uid)
  assert folder_stats.sessions == 1


def test_archive_extraction_writes_wanted_members_and_digests_every_one(tmp_path: Path) -> None:
  path = tmp_path / 'bundle.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('logs/first.jsonl', 'one')
    archive.writestr('logs/second.txt', 'two')
  destination = tmp_path / 'out'

  contents = archive_handler.extract_sync(path, destination, [PurePosixPath('logs/first.jsonl')])

  assert set(contents.files) == {PurePosixPath('logs/first.jsonl')}
  assert contents.files[PurePosixPath('logs/first.jsonl')].read_text(encoding='utf-8') == 'one'
  assert set(contents.digests) == {PurePosixPath('logs/first.jsonl'), PurePosixPath('logs/second.txt')}
  assert contents.digests[PurePosixPath('logs/second.txt')] == hashlib.md5(b'two').hexdigest()
  assert contents.errors == ()


def test_archive_extraction_takes_every_file_member_by_default(tmp_path: Path) -> None:
  path = tmp_path / 'bundle.tar.gz'
  source = tmp_path / 'src'
  (source / 'inner').mkdir(parents=True)
  (source / 'inner' / 'note.md').write_text('body', encoding='utf-8')
  with tarfile.open(path, 'w:gz') as archive:
    archive.add(source / 'inner', arcname='inner')
  destination = tmp_path / 'out'

  contents = archive_handler.extract_sync(path, destination)

  assert set(contents.files) == {PurePosixPath('inner/note.md')}
  assert contents.digests[PurePosixPath('inner/note.md')] == hashlib.md5(b'body').hexdigest()


def test_archive_extraction_of_an_unreadable_member_is_an_error_not_the_end(tmp_path: Path) -> None:
  path = tmp_path / 'bundle.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('broken.txt', 'one')
    archive.writestr('good.txt', 'two')
  data = bytearray(path.read_bytes())
  data[data.index(b'one')] = data[data.index(b'one')] ^ 0xFF   # the stored bytes no longer match their CRC
  path.write_bytes(bytes(data))

  contents = archive_handler.extract_sync(path, tmp_path / 'out')

  assert [error.path for error in contents.errors] == [PurePosixPath('broken.txt')]
  assert set(contents.files) == {PurePosixPath('good.txt')}


def _chromium_profile(folder: Path, visits: tuple[int, ...]) -> Path:
  """A Chromium profile: the History database its browser writes, and a Bookmarks file beside it."""
  folder.mkdir(parents=True, exist_ok=True)
  database = folder / 'History'
  connection = sqlite3.connect(database)
  with connection:
    connection.execute('CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, last_visit_time INTEGER)')
    connection.execute('CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)')
    connection.execute('CREATE TABLE downloads (id INTEGER PRIMARY KEY, start_time INTEGER)')
    connection.execute("INSERT INTO urls VALUES (1, 'https://example.test', ?)", (visits[0],))
    connection.executemany('INSERT INTO visits VALUES (NULL, 1, ?)', [(value,) for value in visits])
    connection.execute('INSERT INTO downloads VALUES (NULL, ?)', (visits[-1],))
  connection.close()   # sqlite3's context manager commits; it does not close, and Windows will not remove an open file
  (folder / 'Bookmarks').write_text(json.dumps({'roots': {'bar': {'type': 'folder', 'children': [
    {'type': 'url', 'date_added': str(visits[0])},
    {'type': 'folder', 'children': [{'type': 'url', 'date_added': str(visits[-1])}]},
  ]}}}), encoding='utf-8')
  return database


def test_browser_handler_reads_a_chromium_profile_from_its_folder(tmp_path: Path) -> None:
  moment = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
  microseconds = int((moment - datetime(1601, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1_000_000)
  folder = tmp_path / 'Google' / 'Chrome' / 'User Data' / 'Default'
  _chromium_profile(folder, (microseconds, microseconds + 86_400_000_000))

  handler = BrowserHandler()
  assert handler.identify_sync(folder)                       # the profile folder answers for the database in it
  assert handler.identify_sync(folder / 'History')
  assert not handler.identify_sync(folder / 'Bookmarks')

  stats, profile = handler.call_sync(folder)
  assert (profile.family, profile.browser, profile.profile) == ('chromium', 'chrome', 'Default')
  assert (profile.history, profile.urls, profile.favorites, profile.downloads) == (2, 1, 2, 1)
  assert _bounds(stats.span) == (moment, moment + timedelta(days=1))
  assert profile.metadata['history'] == 2 and 'url' not in profile.metadata


def test_browser_handler_reads_a_firefox_profile_and_leaves_the_original_alone(tmp_path: Path) -> None:
  moment = datetime(2026, 7, 3, 9, tzinfo=timezone.utc)
  microseconds = int(moment.timestamp() * 1_000_000)
  folder = tmp_path / 'Mozilla' / 'Firefox' / 'Profiles' / 'abc.default'
  folder.mkdir(parents=True)
  database = folder / 'places.sqlite'
  connection = sqlite3.connect(database)
  with connection:
    connection.execute('CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT)')
    connection.execute('CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, visit_date INTEGER)')
    connection.execute('CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INTEGER, dateAdded INTEGER)')
    connection.execute("INSERT INTO moz_places VALUES (1, 'https://example.test')")
    connection.execute('INSERT INTO moz_historyvisits VALUES (NULL, ?)', (microseconds,))
    connection.execute('INSERT INTO moz_bookmarks VALUES (NULL, 1, ?)', (microseconds,))
  connection.close()
  before = database.read_bytes()

  stats, profile = BrowserHandler().call_sync(folder)

  assert (profile.family, profile.browser, profile.profile) == ('firefox', 'firefox', 'abc.default')
  assert (profile.history, profile.urls, profile.favorites, profile.downloads) == (1, 1, 1, 0)
  assert _bounds(stats.span) == (moment, moment)
  assert database.read_bytes() == before                     # the profile is read through a copy, never in place


def test_browser_handler_leaves_anything_that_is_not_a_profile_unrecognized(tmp_path: Path) -> None:
  (tmp_path / 'History').write_text('not a database', encoding='utf-8')
  (tmp_path / 'notes').mkdir()

  handler = BrowserHandler()
  assert not handler.identify_sync(tmp_path / 'History')
  assert not handler.identify_sync(tmp_path / 'notes')
  with pytest.raises(ValueError, match='not a browser profile'):
    handler.call_sync(tmp_path / 'notes')


def test_a_filesystem_root_is_never_ignored(tmp_path: Path) -> None:
  root = Path(tmp_path.anchor)
  assert IgnoredHandler.reason(root) is None
  assert IgnoredHandler().identify_sync(root) is False



def test_a_dot_folder_is_walked_and_venv_and_git_are_not(tmp_path: Path) -> None:
  """Alex, 2026-09-17 03:51: "all files can be potentially indexd., It is critical that secrets are
  indexed. I have lost lots of secrets because of ignored dot files" and "venv, .git are ignored".
  So the dot prefix is not a rule and the hidden attribute is not a rule; the named list is."""

  class TreeHandler(FileHandler, IgnoredHandler, FolderHandler):
    pass

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

  found = {record.path: record for record in TreeHandler().probe(tmp_path)}

  assert store / 'session.jsonl' in found
  assert secrets / 'id_ed25519' in found
  assert 'ignored' not in found[tmp_path / '.claude'].handlers
  assert 'ignored' not in found[secrets].handlers
  for name in ('.git', 'venv', '.venv'):
    assert found[tmp_path / name].handlers == ('ignored', 'folder')
    assert tmp_path / name / 'inside.txt' not in found


def test_a_gemini_cli_chat_is_read_as_itself(tmp_path: Path) -> None:
  """Its header carries a sessionId, which is the whole Claude Code test, so without a reader of its
  own it is read as Claude Code: no turns, and every chat of one service under the service's id."""

  class TreeHandler(FileHandler, SessionHandler):
    pass

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

  handler = TreeHandler()
  readings = [handler.call_sync(path)[1] for path in (first, second)]
  assert [one.harness for one in readings] == ['gemini', 'gemini']
  assert readings[0].uid != readings[1].uid, 'one service id must not fold two chats into one'
  assert readings[0].uid == 'a2a-server/2026-08-24T13:51:09.797Z'
  assert [len(one.turns) for one in readings] == [1, 1]
  assert readings[0].turns[0].text == 'first'
  assert all(one.span is not None for one in readings)


def test_the_session_cache_does_not_grow_without_bound(tmp_path: Path) -> None:
  """A walk reads each session once, so an unbounded cache holds every transcript of the location.
  On a folder of 166,040 sessions that is the folder, in memory, and a run of it stops writing."""

  class TreeHandler(FileHandler, SessionHandler):
    pass

  handler = TreeHandler()
  handler._session_cache_limit = 8
  for number in range(20):
    path = tmp_path / f'{number}.jsonl'
    path.write_text(json.dumps(
      {'sessionId': f'session-{number}', 'type': 'user', 'uuid': f'u{number}',
       'timestamp': '2026-09-17T00:00:00Z', 'message': {'role': 'user', 'content': 'hello'}}),
      encoding='utf-8')
    handler.call_sync(path)
    assert len(handler._session_cache) <= 8

  # What is still cached is what was read last, and a session read again is still read correctly.
  last = tmp_path / '19.jsonl'
  assert last in handler._session_cache
  assert handler.call_sync(last)[1].uid == 'session-19'
  assert handler.call_sync(tmp_path / '0.jsonl')[1].uid == 'session-0'


def test_a_sqlite_file_is_read_as_material(tmp_path: Path) -> None:
  """Alex's rule for an old location index: it is discovered material, read like a .rar file and
  never written, read once via handler and never reopened. So an index standing beside files now
  sealed in an archive is still known â€” what it indexed and what it recorded â€” without opening it."""
  import sqlite3

  from gppu.handlers import SqliteHandler

  database = tmp_path / 'old-index.sqlite'
  with sqlite3.connect(database) as connection:
    connection.execute('CREATE TABLE records (uid TEXT PRIMARY KEY, path TEXT, size INTEGER)')
    connection.execute('CREATE TABLE spans (uid TEXT, first TEXT, last TEXT)')
    connection.execute("INSERT INTO records VALUES ('a', 'x.md', 10)")
  (tmp_path / 'note.md').write_text('not a database', encoding='utf-8')

  handler = SqliteHandler()
  assert handler.identify_sync(database) is True
  assert handler.identify_sync(tmp_path / 'note.md') is False, 'the bytes are asked, not the name'

  stats, read = handler.call_sync(database)
  assert read.tables == ('records', 'spans')
  assert read.columns['records'] == ('uid', 'path', 'size')
  assert read.metadata['tables'] == ['records', 'spans']
  assert stats.bytes == database.stat().st_size
  # Opened immutable, so SQLite writes neither companion beside a file in a synced folder.
  assert sorted(path.name for path in tmp_path.iterdir()) == ['note.md', 'old-index.sqlite']


def test_ten_digits_that_are_not_a_time_do_not_stop_a_walk(tmp_path):
  """A ten-digit number in a name is as likely to be an account number as a timestamp."""
  from gppu.handlers import FileHandler, FolderHandler

  class Files(FileHandler, FolderHandler):
    pass

  for name in ('order 9999999999.pdf', 'statement 1600000000.pdf', 'acct 4111111111.csv'):
    (tmp_path / name).write_text('x', encoding='utf-8')
  found = {record.name: record for record in Files().identify_sync(tmp_path)}
  assert set(found) >= {'order 9999999999.pdf', 'statement 1600000000.pdf', 'acct 4111111111.csv'}
  assert FileHandler._name_span('order 9999999999.pdf') is None, 'a year-2286 number is not a time'
  assert FileHandler._name_span('statement 1600000000.pdf') is not None, 'a real epoch still reads'


def test_a_name_spelling_a_date_this_host_cannot_place_does_not_stop_a_walk(tmp_path):
  """A far date in a name is a number shaped like a date; a hierarchy walk does not stop for it."""
  from gppu.handlers import FileHandler, FolderHandler

  class Files(FileHandler, FolderHandler):
    pass

  for name in ('scan 2999-12-31.jpg', 'scan 9999-12-31.jpg', 'note 2024-03-05.md'):
    (tmp_path / name).write_text('x', encoding='utf-8')
  found = {record.name for record in Files().identify_sync(tmp_path)}
  assert {'scan 2999-12-31.jpg', 'scan 9999-12-31.jpg', 'note 2024-03-05.md'} <= found
  assert FileHandler._name_span('scan 9999-12-31.jpg') is None
  assert FileHandler._name_span('note 2024-03-05.md') is not None, 'a real date still reads'
