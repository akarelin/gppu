from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from gppu.handlers import ArchiveHandler, GppuCatalog, GppuFileSystem


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
  live = fs.ls(recurse=True, refresh=True)
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


def test_ls_identifies_without_probing_and_refresh_probes(tmp_path, monkeypatch):
  folder = tmp_path / 'notes'
  folder.mkdir()
  (folder / 'note.md').write_text('---\ntitle: Handlers\n---\nText', encoding='utf-8')
  fs = GppuFileSystem(tmp_path)
  root = fs.info()
  assert root['gppu']['probed'] is False
  assert root['gppu']['files'] is None
  assert index(tmp_path).is_file()
  listed = fs.ls(recurse=True)
  assert [row['gppu']['name'] for row in listed] == ['notes', 'note.md']
  assert all(row['gppu']['probed'] is False for row in listed)
  note = listed[1]
  assert note['gppu']['handlers'] == ['markdown']
  assert note['gppu']['bytes'] == note['size']
  assert note['gppu']['modified_at'] == str(datetime.fromtimestamp((folder / 'note.md').stat().st_mtime).astimezone())
  assert note['gppu']['span'] == [note['gppu']['modified_at']] * 2
  assert 'markdown' not in note['gppu']
  assert listed[0]['gppu']['files'] is None
  (tmp_path / 'added.txt').write_text('added')
  assert [row['gppu']['name'] for row in fs.ls()] == ['notes', 'added.txt']
  assert note['gppu']['probed_at'] is None
  detail = fs.info(note['name'])
  assert detail['gppu']['probed'] is True
  assert detail['gppu']['markdown']['title'] == 'Handlers'
  assert datetime.fromisoformat(detail['gppu']['probed_at']).utcoffset() == datetime.now().astimezone().utcoffset()
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert fs.info(note['name']) == detail
  monkeypatch.undo()
  fs.ls(refresh=True, recurse=True)
  assert fs.info()['gppu']['files'] == 2
  assert fs.info('notes')['gppu']['probed'] is True


def test_ls_lists_removed_and_added_entries_and_refresh_forgets_removed(tmp_path):
  source = tmp_path / 'old.txt'
  source.write_text('old')
  fs = GppuFileSystem(tmp_path)
  fs.ls()
  source.unlink()
  (tmp_path / 'new.txt').write_text('new content')
  listed = fs.ls()
  assert [row['gppu']['name'] for row in listed] == ['new.txt']
  assert listed[0]['gppu']['probed'] is False
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
def test_child_refresh_updates_ancestor_totals_from_cached_siblings(tmp_path, monkeypatch, shard):
  child = tmp_path / 'outer' / 'child'
  child.mkdir(parents=True)
  (child / 'old-2020-01-01.txt').write_text('old')
  sibling = tmp_path / 'sibling.txt'
  sibling.write_text('cached sibling')
  if shard:
    GppuFileSystem(child).ls()
  fs = GppuFileSystem(tmp_path)
  fs.ls(recurse=True, refresh=True)
  sibling_before = fs.info('sibling.txt')
  sibling.write_text('changed but not refreshed')
  (child / 'old-2020-01-01.txt').unlink()
  nested = child / 'nested'
  nested.mkdir()
  (nested / 'new-2026-01-01.txt').write_text('new content')
  (child / 'second.txt').write_text('second')
  calls = []
  live = fs._live
  def scoped_live(key):
    calls.append(key)
    assert key == 'outer/child', 'Refresh reparsed outside the requested subtree'
    live(key)
  monkeypatch.setattr(fs, '_live', scoped_live)
  fs.ls('outer/child', refresh=True)
  assert calls == ['outer/child']
  assert fs.info('sibling.txt') == sibling_before
  for path, expected in (
    ('outer/child', (2, 1, 17)),
    ('outer', (2, 2, 17)),
    (None, (3, 3, 31)),
  ):
    metadata = fs.info(path)['gppu']
    assert tuple(metadata[field] for field in ('files', 'folders', 'bytes')) == expected
    assert metadata['span'][0].startswith('2026-01-01')
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem(tmp_path).info() == fs.info()


def test_caching_a_new_child_updates_its_cached_parent_listing(tmp_path):
  (tmp_path / 'before.txt').write_text('before')
  fs = GppuFileSystem(tmp_path)
  fs.ls()
  (tmp_path / 'added.txt').write_text('added')
  added = fs.info('added.txt')
  assert added['gppu']['probed'] is True
  assert [row['gppu']['name'] for row in fs.ls()] == ['added.txt', 'before.txt']
  assert fs.info()['gppu']['files'] == 2
  assert fs.info()['gppu']['bytes'] == 11


def test_refresh_rereads_metadata_when_size_and_mtime_are_unchanged(tmp_path):
  note = tmp_path / 'note.md'
  note.write_text('---\ntitle: Before\n---\nText', encoding='utf-8')
  fs = GppuFileSystem(tmp_path)
  before, = fs.ls()
  status = note.stat()
  note.write_text('---\ntitle: After!\n---\nText', encoding='utf-8')
  os.utime(note, ns=(status.st_atime_ns, status.st_mtime_ns))
  assert fs.ls() == [before]
  assert fs.info('note.md', refresh=True)['gppu']['markdown']['title'] == 'After!'


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
  fs.ls(recurse=True, refresh=True)
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
  GppuFileSystem(old).ls(refresh=True)
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
def test_entering_an_archive_identifies_members_and_refresh_probes_them(tmp_path, monkeypatch, extension):
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
  assert [row['gppu']['name'] for row in rows] == ['inside', 'note.md']
  folder, note = rows
  assert all(row['gppu']['probed'] is False for row in rows)
  assert folder['gppu']['files'] is None
  assert note['gppu']['handlers'] == ['markdown']
  assert note['gppu']['bytes'] == len(content)
  assert 'markdown' not in note['gppu']
  assert fs.info(path.name)['gppu']['is_container']
  assert fs.info(note['gppu']['parent'])['type'] == 'directory'
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem(tmp_path).ls(path.name, recurse=True) == rows
  assert fs.ls(folder['name']) == [note]
  monkeypatch.undo()
  detail = fs.info(note['name'])
  assert detail['gppu']['probed'] is True
  assert detail['gppu']['markdown']['title'] == 'Inside archive'
  assert fs.info(folder['name'])['gppu']['files'] is None
  probed = fs.ls(path.name, recurse=True, refresh=True)
  assert all(row['gppu']['probed'] is True for row in probed)
  assert probed[0]['gppu']['files'] == 1
  assert probed[1]['gppu']['markdown']['title'] == 'Inside archive'
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem(tmp_path).ls(path.name, recurse=True) == probed


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
  assert [row['gppu']['name'] for row in before] == ['old', 'outer.zip', 'inner.zip', 'note.md']
  assert before[-1]['gppu']['handlers'] == ['markdown']
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  after = fs.ls(recurse=True)
  assert all('/old/' not in row['name'] for row in after)
  assert [row['gppu']['name'] for row in after] == ['new', 'outer.zip', 'inner.zip', 'note.md']
  monkeypatch.undo()
  assert fs.info(after[-1]['name'])['gppu']['markdown']['title'] == 'Nested'


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
  listed = fs.ls('bundle.rar', recurse=True)
  note = next(row for row in listed if row['gppu']['name'] == 'note.md')
  assert note['gppu']['handlers'] == ['markdown']
  assert note['gppu']['probed'] is False
  assert fs.info(note['name'])['gppu']['markdown']['title'] == 'RAR metadata'
  after = fs.ls('bundle.rar', recurse=True)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem(tmp_path).ls('bundle.rar', recurse=True) == after


def test_session_paths_inside_archives_are_source_uris(tmp_path):
  path = tmp_path / 'session.jsonl'
  session(path)
  with zipfile.ZipFile(tmp_path / 'sessions.zip', 'w') as archive:
    archive.writestr('session.jsonl', path.read_bytes())
  fs = GppuFileSystem(tmp_path)
  row, = fs.ls('sessions.zip')
  assert row['gppu']['handlers'] == ['session']
  detail = fs.info(row['name'])
  assert detail['gppu']['session']['path'] == detail['name']
  assert fs.info('zip://::sessions.zip')['gppu']['files'] is None
  fs.ls('sessions.zip', refresh=True)
  assert fs.info('zip://::sessions.zip')['gppu']['files'] == 1


@pytest.mark.parametrize('location', ['.', 'folder'])
def test_relative_location_is_refused_and_creates_nothing(tmp_path, monkeypatch, location):
  monkeypatch.chdir(tmp_path)
  with pytest.raises(ValueError, match='absolute'):
    GppuFileSystem(location)
  assert list(tmp_path.iterdir()) == []


def test_a_folder_the_account_cannot_list_is_still_listed_by_its_parent(tmp_path, monkeypatch):
  locked = tmp_path / 'System Volume Information'
  locked.mkdir()
  (tmp_path / 'open.txt').write_text('open')
  from fsspec.implementations.local import LocalFileSystem
  original = LocalFileSystem.ls
  def denied(self, path, detail=True, **kwargs):
    if Path(path).resolve() == locked.resolve():
      raise PermissionError(5, 'Access is denied', str(path))
    return original(self, path, detail=detail, **kwargs)
  monkeypatch.setattr(LocalFileSystem, 'ls', denied)
  rows = GppuFileSystem(tmp_path).ls()
  assert [row['gppu']['name'] for row in rows] == ['System Volume Information', 'open.txt']
  with pytest.raises(PermissionError):
    GppuFileSystem(tmp_path).ls('System Volume Information')


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
  fs.ls(refresh=True)
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  metadata = fs.info('new/export.zip')
  exported, = metadata['gppu']['claude']['sessions']
  assert exported['location'] == metadata['name']
  assert exported['path'] == 'conversations.json'


def catalog_of(tmp_path: Path, rows: list[dict]) -> Path:
  folder = tmp_path / '.catalog'
  folder.mkdir(exist_ok=True)
  (folder / 'locations.json').write_text(json.dumps(rows), encoding='utf-8')
  return folder


def location_row(number: int, root: Path, parent: int | None = None) -> dict:
  return {'id': number, 'path': root.name, 'parent_file_location_id': parent, 'root_path': str(root),
    'index': str(root / f'.{root.name}.gppufs.sqlite')}


def test_catalog_lists_locations_and_serves_each_through_its_own_index(tmp_path):
  outer = tmp_path / 'outer'
  inner = outer / 'inner'
  inner.mkdir(parents=True)
  (outer / 'a.txt').write_text('a')
  (inner / 'b.md').write_text('---\ntitle: B\n---\nText')
  catalog = GppuCatalog(catalog_of(tmp_path, [location_row(1, outer), location_row(2, inner, 1)]))
  root = catalog.info()
  assert root['gppu']['parent'] is None
  assert root['gppu']['locations'] == 2
  rows = catalog.ls()
  assert [row['gppu']['name'] for row in rows] == ['outer', 'inner']
  assert [row['gppu']['location']['id'] for row in rows] == [1, 2]
  assert [row['gppu']['parent'] for row in rows] == [root['name'], rows[0]['name']]
  assert all(row['gppu']['indexed'] is False for row in rows)
  assert not index(outer).exists()
  detail = catalog.info(rows[0]['name'])
  assert detail['gppu']['probed'] is False
  assert detail['gppu']['parent'] == root['name']
  assert detail['gppu']['location']['id'] == 1
  assert index(outer).is_file()
  assert [row['gppu']['name'] for row in catalog.ls(rows[0]['name'])] == ['inner', 'a.txt']
  assert catalog.info(rows[1]['name'])['gppu']['parent'] == rows[0]['name']
  assert catalog.ls(rows[1]['name'])[0]['gppu']['handlers'] == ['markdown']
  assert index(inner).is_file()
  assert catalog.ls()[1]['gppu']['indexed'] is True
  assert catalog.info()['gppu']['files'] is None
  assert catalog.info()['gppu']['indexed'] == 2
  catalog.ls(rows[0]['name'], refresh=True)
  outer_row, inner_row = catalog.ls()
  assert (outer_row['gppu']['files'], outer_row['gppu']['folders'], outer_row['gppu']['probed']) == (2, 1, True)
  assert (inner_row['gppu']['files'], inner_row['gppu']['probed']) == (1, True)
  summary = catalog.info()['gppu']
  assert (summary['files'], summary['folders'], summary['bytes']) == (2, 1, outer_row['gppu']['bytes'])
  assert summary['probed_at'] == max(outer_row['gppu']['probed_at'], inner_row['gppu']['probed_at'])
  assert summary['span'] == outer_row['gppu']['span']
  assert [row['gppu']['name'] for row in catalog.ls(recurse=True)] == ['outer', 'inner', 'b.md', 'a.txt']
  assert catalog.ls(detail=False) == [row['name'] for row in rows]
  with pytest.raises(FileNotFoundError, match='not inside'):
    catalog.info(str(tmp_path / 'elsewhere'))
  with pytest.raises(ValueError, match='absolute'):
    catalog.info('relative/name')
  third = tmp_path / 'third'
  third.mkdir()
  catalog_of(tmp_path, [location_row(1, outer), location_row(2, inner, 1), location_row(3, third)])
  assert len(catalog.ls()) == 2
  assert len(catalog.ls(refresh=True)) == 3


def test_catalog_refuses_an_index_that_is_not_where_gppufs_keeps_it(tmp_path):
  outer = tmp_path / 'outer'
  outer.mkdir()
  row = {**location_row(1, outer), 'index': str(tmp_path / 'elsewhere.sqlite')}
  with pytest.raises(ValueError, match='catalog index'):
    GppuCatalog(catalog_of(tmp_path, [row]))

