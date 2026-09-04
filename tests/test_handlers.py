from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

import pytest
import gppu.handlers as handlers_module
from gppu import OSType, detect_os

from gppu.handlers import (
  typed,
  ArchiveHandler,
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
  assert _iso(stats.span) == [
    '2026-08-01T12:00:00+00:00',
    '2026-08-01T12:02:00+00:00',
  ]
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
  assert _iso(stats.span) == [
    '2026-08-01T12:00:00+00:00',
    '2026-08-01T12:02:00+00:00',
  ]


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
  assert stats == FileStats(0, 0, 0, None)
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
  assert _iso(markdown.span) == [
    '2026-08-27T19:42:00-07:00',
    '2026-09-01T05:11:00-07:00',
  ]
  assert stats == FileStats(1, 0, path.stat().st_size, markdown.span)
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
  assert stats == FileStats(1, 0, path.stat().st_size, None)
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

  assert _iso(table.span) == [
    '2026-08-27T19:42:00-07:00',
    '2026-09-01T05:11:00-07:00',
  ]
  assert stats.span == table.span


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
  assert _iso(log.span) == [
    '2026-09-04T08:00:00-07:00',
    '2026-09-04T09:15:30.500000-07:00',
  ]
  assert stats == FileStats(1, 0, path.stat().st_size, log.span)
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
  assert stats.span == email.span
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
  assert probed[0].stats == FileStats(1, 1, 3, probed[0].span)


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
    assert (await file_handler.probe(session_path, recursive=False))[0].span == stats.span
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
  assert _iso(found[repository].span) == [
    '2026-06-01T11:00:00+00:00',
    '2026-08-02T13:00:00+00:00',
  ]
  assert found[nested].span == found[repository].span
  assert _iso(found[first].span) == [
    '2026-07-01T12:00:00+00:00',
    '2026-08-02T13:00:00+00:00',
  ]
  assert _iso(found[second].span) == [
    '2026-08-02T13:00:00+00:00',
    '2026-08-02T13:00:00+00:00',
  ]
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
    assert stats.span == found[first].span
    assert metadata.metadata_path == repository / '.git'

  asyncio.run(exercise())

  first.write_text('changed again', encoding='utf-8')
  _git_commit(repository, 'third', '2026-09-03T14:00:00+00:00')
  assert _iso(handler.probe(first, recursive=False)[0].span) == [
    '2026-07-01T12:00:00+00:00',
    '2026-09-03T14:00:00+00:00',
  ]


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

  assert probe.stats == FileStats(1, 0, source.stat().st_size, probe.stats.span)
  assert probe.stats.span[0].astimezone(timezone.utc).date().isoformat() == '2026-08-20'


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
