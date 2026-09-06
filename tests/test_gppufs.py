from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from gppu.handlers import ArchiveHandler, GppuFileSystem


def index(folder: Path) -> Path:
  return folder / f'.{folder.name}.gppufs.sqlite'


def session(path: Path) -> None:
  path.write_text('\n'.join(json.dumps(row) for row in (
    {'type': 'session_meta', 'timestamp': '2026-09-01T08:00:00Z', 'payload': {'id': 'codex-demo'}},
    {'type': 'response_item', 'timestamp': '2026-09-01T08:01:00Z', 'payload': {
      'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Show the handlers'}]}},
  )), encoding='utf-8')


def no_live(*args, **kwargs):
  raise AssertionError('Cached metadata was reparsed')


def rename(source: Path, destination: Path, boundary: Path) -> None:
  assert source.resolve().is_relative_to(boundary.resolve())
  assert destination.resolve().is_relative_to(boundary.resolve())
  source.rename(destination)


def test_live_and_sqlite_return_all_metadata(tmp_path, monkeypatch):
  folder = tmp_path / 'notes'
  folder.mkdir()
  (folder / 'note.md').write_text('---\ntitle: Handlers\nstats: user metadata\ncreated: 2026-09-01\n---\nText', encoding='utf-8')
  session(folder / 'session.jsonl')
  fs = GppuFileSystem(tmp_path)
  live = fs.ls(recurse=True)
  root = fs.info()
  assert root['gppu']['files'] == 2
  assert root['gppu']['folders'] == 1
  note = next(row for row in live if row['name'].endswith('/note.md'))
  assert note['gppu']['markdown']['title'] == 'Handlers'
  assert note['gppu']['markdown']['stats'] == 'user metadata'
  parsed = next(row for row in live if row['name'].endswith('/session.jsonl'))
  assert parsed['gppu']['session']['uid'] == 'codex-demo'
  assert parsed['gppu']['session']['path'] == parsed['name']
  assert parsed['gppu']['session']['turns'] == 1
  assert index(tmp_path).is_file()
  with sqlite3.connect(index(tmp_path)) as database:
    stored = database.execute("SELECT metadata FROM gppufs_entries WHERE path='notes/session.jsonl'").fetchone()[0]
    assert json.loads(stored)['gppu']['session']['path'] == 'notes/session.jsonl'
  assert not index(folder).exists()
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  cached = GppuFileSystem(tmp_path)
  assert cached.ls(recurse=True) == live
  assert cached.info() == root
  assert cached.info(note['name']) == note
  assert cached.ls(detail=False) == [row['name'] for row in cached.ls()]


def test_refresh_replaces_snapshot_and_excludes_indexes(tmp_path):
  source = tmp_path / 'old.txt'
  source.write_text('old')
  fs = GppuFileSystem(tmp_path)
  before = fs.ls()
  source.unlink()
  (tmp_path / 'new.txt').write_text('new content')
  assert fs.ls() == before
  fresh = fs.ls(refresh=True)
  assert [row['gppu']['name'] for row in fresh] == ['new.txt']
  assert fs.info()['gppu']['bytes'] == len('new content')
  with pytest.raises(FileNotFoundError):
    fs.info('old.txt')


def test_failed_refresh_does_not_destroy_snapshot(tmp_path, monkeypatch):
  (tmp_path / 'note.txt').write_text('cached')
  fs = GppuFileSystem(tmp_path)
  before = fs.ls()
  def denied(*args, **kwargs):
    raise PermissionError('source unavailable')
  monkeypatch.setattr(fs, '_inventory', denied)
  with pytest.raises(PermissionError, match='source unavailable'):
    fs.ls(refresh=True)
  assert fs.ls() == before


@pytest.mark.parametrize('shard', [False, True])
@pytest.mark.parametrize('method', ['ls', 'info'])
def test_folder_rename_preserves_rows(tmp_path, monkeypatch, shard, method):
  outer = tmp_path / 'outer'
  outer.mkdir()
  old = outer / 'old'
  old.mkdir()
  session(old / 'session.jsonl')
  (old / 'note.md').write_text('---\npath: old/user-authored-value\n---\nText')
  if shard:
    GppuFileSystem(old).ls()
  fs = GppuFileSystem(tmp_path)
  fs.ls(recurse=True)
  before = fs.info('outer/old/session.jsonl')
  new = outer / 'renamed'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  if method == 'ls':
    rows = fs.ls('outer')
    assert [row['gppu']['name'] for row in rows] == ['renamed']
  else:
    assert fs.info('outer/renamed')['gppu']['name'] == 'renamed'
  after = fs.info('outer/renamed/session.jsonl')
  assert after['ino'] == before['ino']
  assert after['gppu']['session']['uid'] == 'codex-demo'
  assert after['gppu']['session']['path'] == after['name']
  assert '/outer/renamed/' in after['name']
  assert fs.info('outer/renamed/note.md')['gppu']['markdown']['path'] == 'old/user-authored-value'
  if not shard:
    with sqlite3.connect(index(tmp_path)) as database:
      value = json.loads(database.execute(
        "SELECT metadata FROM gppufs_entries WHERE path='outer/renamed/session.jsonl'").fetchone()[0])
      assert value['name'] == value['gppu']['path'] == 'outer/renamed/session.jsonl'
  if shard:
    assert index(new).is_file()
    assert not (new / '.old.gppufs.sqlite').exists()
    with sqlite3.connect(index(tmp_path)) as database:
      assert database.execute("SELECT path FROM gppufs_entries WHERE path LIKE 'outer/old/%'").fetchall() == []


def test_location_rename_renames_database_without_reindexing(tmp_path, monkeypatch):
  old = tmp_path / 'original'
  old.mkdir()
  session(old / 'session.jsonl')
  GppuFileSystem(old).ls()
  contents = index(old).read_bytes()
  new = tmp_path / 'renamed'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  fs = GppuFileSystem(new)
  assert fs.info()['gppu']['name'] == 'renamed'
  assert fs.ls()[0]['gppu']['session']['path'] == fs.ls()[0]['name']
  assert index(new).read_bytes() == contents
  assert not (new / '.original.gppufs.sqlite').exists()


def test_location_rename_after_info_without_root_listing(tmp_path, monkeypatch):
  old = tmp_path / 'old'
  old.mkdir()
  (old / 'file.txt').write_text('cached')
  GppuFileSystem(old).info('file.txt')
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem(new).info('file.txt')['gppu']['bytes'] == 6
  assert index(new).is_file()


def test_refresh_renamed_folder_updates_existing_paths(tmp_path):
  old = tmp_path / 'old'
  old.mkdir()
  (old / 'file.txt').write_text('cached')
  fs = GppuFileSystem(tmp_path)
  fs.ls()
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  (new / 'file.txt').write_text('changed')
  assert fs.ls('new', refresh=True)[0]['gppu']['bytes'] == 7
  assert [row['gppu']['name'] for row in fs.ls()] == ['new']


def test_case_only_folder_rename_updates_index_filename(tmp_path, monkeypatch):
  old = tmp_path / 'MixedCase'
  old.mkdir()
  (old / 'file.txt').write_text('cached')
  GppuFileSystem(old).ls()
  fs = GppuFileSystem(tmp_path)
  fs.ls()
  new = tmp_path / 'MIXEDCASE'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert fs.ls()[0]['gppu']['name'] == 'MIXEDCASE'
  assert index(new).name in [path.name for path in new.iterdir()]
  assert '.MixedCase.gppufs.sqlite' not in [path.name for path in new.iterdir()]
  assert fs.ls('MIXEDCASE')[0]['gppu']['bytes'] == 6


@pytest.mark.parametrize('extension', ['zip', 'tar.gz'])
def test_archives_are_listable_with_cached_member_metadata(tmp_path, monkeypatch, extension):
  path = tmp_path / ('bundle.' + extension)
  content = b'---\ntitle: Inside archive\n---\nText'
  if extension == 'zip':
    with zipfile.ZipFile(path, 'w') as archive:
      archive.writestr('inside/note.md', content)
  else:
    with tarfile.open(path, 'w:gz') as archive:
      member = tarfile.TarInfo('inside/note.md')
      member.size = len(content)
      archive.addfile(member, io.BytesIO(content))
  fs = GppuFileSystem(tmp_path)
  rows = fs.ls(path.name, recurse=True)
  assert len(rows) == 2
  note = next(row for row in rows if row['name'].split('::')[0].endswith('note.md'))
  assert note['gppu']['markdown']['title'] == 'Inside archive'
  assert fs.info(note['name']) == note
  assert fs.info(path.name)['gppu']['is_container']
  assert fs.info(note['gppu']['parent'])['type'] == 'directory'
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem(tmp_path).ls(path.name, recurse=True) == rows


def test_nonlocal_fsspec_location_keeps_sqlite_beside_source(tmp_path, monkeypatch):
  native = MemoryFileSystem()
  root = '/' + tmp_path.name
  native.makedirs(root)
  native.pipe_file(root + '/note.md', b'---\ntitle: Remote\n---\nText')
  fs = GppuFileSystem('memory://' + root)
  before = fs.ls()
  assert before[0]['gppu']['markdown']['title'] == 'Remote'
  assert native.cat_file(root + '/.' + tmp_path.name + '.gppufs.sqlite').startswith(b'SQLite format 3')
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem('memory://' + root).ls() == before


@pytest.mark.parametrize('extension', ['zip', 'tar.gz'])
def test_empty_archive_is_an_empty_listing(tmp_path, extension):
  path = tmp_path / ('empty.' + extension)
  if extension == 'zip':
    with zipfile.ZipFile(path, 'w'):
      pass
  else:
    with tarfile.open(path, 'w:gz'):
      pass
  assert GppuFileSystem(tmp_path).ls(path.name) == []


def test_nested_archives_retain_addresses_after_folder_rename(tmp_path, monkeypatch):
  old = tmp_path / 'old'
  old.mkdir()
  nested = io.BytesIO()
  with zipfile.ZipFile(nested, 'w') as archive:
    archive.writestr('note.md', '---\ntitle: Nested\n---\nText')
  with zipfile.ZipFile(old / 'outer.zip', 'w') as archive:
    archive.writestr('inner.zip', nested.getvalue())
  fs = GppuFileSystem(tmp_path)
  before = fs.ls(recurse=True)
  assert len(before) == 4
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  after = fs.ls(recurse=True)
  assert all('/old/' not in row['name'] for row in after)
  assert after[-1]['gppu']['markdown']['title'] == 'Nested'
  assert fs.info(after[-1]['name']) == after[-1]


def test_rar_members_use_existing_handler(tmp_path, monkeypatch):
  try:
    executable = ArchiveHandler.rar_executable()
  except FileNotFoundError as error:
    pytest.skip(str(error))
  folder = tmp_path / 'inside'
  folder.mkdir()
  (folder / 'note.md').write_text('---\ntitle: RAR metadata\n---\nText')
  subprocess.run([str(executable), 'a', '-idq', 'bundle.rar', 'inside'], cwd=tmp_path,
    check=True, capture_output=True)
  fs = GppuFileSystem(tmp_path)
  before = fs.ls('bundle.rar', recurse=True)
  note = next(row for row in before if row['gppu']['name'] == 'note.md')
  assert note['gppu']['markdown']['title'] == 'RAR metadata'
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem(tmp_path).ls('bundle.rar', recurse=True) == before


def test_session_paths_inside_archives_are_source_uris(tmp_path):
  path = tmp_path / 'session.jsonl'
  session(path)
  with zipfile.ZipFile(tmp_path / 'sessions.zip', 'w') as archive:
    archive.writestr('session.jsonl', path.read_bytes())
  fs = GppuFileSystem(tmp_path)
  row, = fs.ls('sessions.zip')
  assert row['gppu']['session']['path'] == row['name']
  assert fs.info('zip://::sessions.zip')['gppu']['files'] == 1


def test_parent_traversal_cannot_escape_location(tmp_path):
  fs = GppuFileSystem(tmp_path)
  for path in ('../outside', fs.location + '/../outside'):
    with pytest.raises(ValueError, match='outside'):
      fs.info(path)


def test_exported_session_member_paths_remain_relative_after_rename(tmp_path, monkeypatch):
  old = tmp_path / 'old'
  old.mkdir()
  with zipfile.ZipFile(old / 'export.zip', 'w') as archive:
    archive.writestr('conversations.json', json.dumps([{'uuid': 'exported-session', 'chat_messages': []}]))
  fs = GppuFileSystem(tmp_path)
  fs.ls()
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  metadata = fs.info('new/export.zip')
  exported, = metadata['gppu']['claude']['sessions']
  assert exported['location'] == metadata['name']
  assert exported['path'] == 'conversations.json'
