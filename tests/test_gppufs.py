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
import yaml
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


def catalog_of(tmp_path: Path, rows: list[dict], sources: dict[str, dict] | None = None, replicas: dict[str, list[dict]] | None = None) -> Path:
  folder = tmp_path / '.catalog'
  (folder / 'test-host').mkdir(parents=True, exist_ok=True)
  (folder / 'test-host' / 'locations.yaml').write_text(yaml.safe_dump(rows, allow_unicode=True), encoding='utf-8')
  for name, source in (sources or {}).items():
    (folder / f'{name}.yaml').write_text(yaml.safe_dump(source, allow_unicode=True), encoding='utf-8')
  if replicas is not None:
    (folder / 'test-host' / 'replicas.yaml').write_text(yaml.safe_dump(replicas, allow_unicode=True), encoding='utf-8')
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
  catalog = GppuCatalog(catalog_of(tmp_path, [location_row(1, outer), location_row(2, inner, 1)]), host='TEST-HOST')
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
    GppuCatalog(catalog_of(tmp_path, [row]), host='test-host')


def test_catalog_needs_a_folder_for_this_host(tmp_path):
  folder = catalog_of(tmp_path, [])
  with pytest.raises(ValueError, match='no folder for host other-host'):
    GppuCatalog(folder, host='other-host')


def test_global_catalog_tells_what_a_folder_is(tmp_path):
  drive = tmp_path / 'drive'
  for name in ('Karelin/Suntrust - Documents', 'Karelin/Notes', 'OneDrive - Karelin/Finance', 'OneDrive - Karelin/Desktop', 'Downloads', 'Plain'):
    (drive / name).mkdir(parents=True)
  finance = 'https://karelin.sharepoint.com/teams/Alex/Finance/'
  sources = {
    'sharepoint': {'locations': [{'name': 'm365-karelin', 'history': '', 'locations': [
      {'name': 'Suntrust - Documents', 'site': 'sites/Suntrust', 'library': 'Shared Documents',
        'origin': 'https://karelin.sharepoint.com/sites/Suntrust/Shared Documents/', 'history': ''},
      {'name': 'Finance', 'site': 'teams/Alex', 'library': 'Finance', 'origin': finance, 'history': 'Household finance since 2019.'},
      {'name': 'OneDrive', 'origin': 'https://karelin-my.sharepoint.com/personal/alex_karelin_com/Documents/', 'locations': [{'name': 'Desktop'}]}]}]},
    'synology-drive': {'locations': [{'name': 's1', 'smb': 'smb://s1', 'locations': [
      {'name': 'Downloads', 'sd': 'sd://s1/Downloads', 'smb': 'smb://s1/Downloads', 'history': ''}]}]},
  }
  seen = '2026-09-08 03:00:00-07:00'
  replicas = {
    'sharepoint': [
      {'location': 'm365-karelin', 'path': str(drive / 'Karelin'), 'checked_at': seen},
      {'location': 'm365-karelin/Suntrust - Documents', 'path': str(drive / 'Karelin' / 'Suntrust - Documents'), 'checked_at': seen},
      {'location': 'm365-karelin/Finance', 'path': str(drive / 'OneDrive - Karelin' / 'Finance'), 'checked_at': seen},
      {'location': 'm365-karelin/OneDrive', 'path': str(drive / 'OneDrive - Karelin'), 'checked_at': None}],
    'synology-drive': [{'location': 's1/Downloads', 'path': str(drive / 'Downloads'), 'checked_at': seen}],
  }
  rows = [location_row(1, drive), location_row(2, drive / 'Downloads', 1)]
  catalog = GppuCatalog(catalog_of(tmp_path, rows, sources, replicas), host='TEST-HOST')
  assert set(catalog.sources) == {'sharepoint', 'synology-drive'}
  listed = {row['gppu']['name']: row['gppu'].get('source') for row in catalog.ls(str(drive))}
  assert listed == {
    'Downloads': {'service': 'synology-drive', 'location': 's1/Downloads', 'server': 's1', 'name': 'Downloads',
      'sd': 'sd://s1/Downloads', 'smb': 'smb://s1/Downloads', 'history': '', 'checked_at': seen},
    'Karelin': {'service': 'sharepoint', 'location': 'm365-karelin', 'name': 'm365-karelin', 'history': '', 'checked_at': seen},
    'OneDrive - Karelin': {'service': 'sharepoint', 'location': 'm365-karelin/OneDrive', 'server': 'm365-karelin', 'name': 'OneDrive',
      'origin': 'https://karelin-my.sharepoint.com/personal/alex_karelin_com/Documents/', 'checked_at': None},
    'Plain': None,
  }
  libraries = {row['gppu']['name']: row['gppu'].get('source') for row in catalog.ls(str(drive / 'Karelin'))}
  assert libraries['Notes'] is None
  assert libraries['Suntrust - Documents']['library'] == 'Shared Documents'
  onedrive = {row['gppu']['name']: row['gppu'].get('source') for row in catalog.ls(str(drive / 'OneDrive - Karelin'))}
  assert onedrive['Desktop'] is None
  assert onedrive['Finance'] == {'service': 'sharepoint', 'location': 'm365-karelin/Finance', 'server': 'm365-karelin', 'name': 'Finance',
    'site': 'teams/Alex', 'library': 'Finance', 'origin': finance, 'history': 'Household finance since 2019.', 'checked_at': seen}
  assert catalog.info(str(drive / 'OneDrive - Karelin' / 'Finance'))['gppu']['source']['origin'] == finance
  downloads = next(row for row in catalog.ls() if row['gppu']['name'] == 'Downloads')
  assert downloads['gppu']['source']['sd'] == 'sd://s1/Downloads'
  assert catalog.info(downloads['name'])['gppu']['source']['server'] == 's1'


def test_a_replica_of_an_unlisted_location_is_refused(tmp_path):
  drive = tmp_path / 'drive'
  drive.mkdir()
  sources = {'dropbox': {'locations': [{'name': 'Dropbox'}]}}
  replicas = {'dropbox': [{'location': 'Elsewhere', 'path': str(drive), 'checked_at': None}]}
  with pytest.raises(ValueError, match='dropbox.yaml does not list'):
    GppuCatalog(catalog_of(tmp_path, [location_row(1, drive)], sources, replicas), host='test-host')


def test_fsspec_initializes_the_instance(tmp_path):
  """`_cached` is fsspec's own guard attribute, so no method may carry that name.

  `AbstractFileSystem.__init__` returns on a truthy `_cached` and leaves the instance without the
  three attributes every read and every transaction goes through.
  """
  fs = GppuFileSystem(tmp_path)
  assert fs._intrans is False
  assert fs._transaction is None
  assert fs.dircache is not None


def test_a_located_file_is_read_and_written_through_the_fsspec_surface(tmp_path):
  text = b'---\ntitle: Read me\n---\nText'
  (tmp_path / 'note.md').write_bytes(text)
  fs = GppuFileSystem(tmp_path)
  assert fs.info('note.md')['gppu']['markdown']['title'] == 'Read me'
  assert fs.cat_file('note.md') == text
  assert fs.head('note.md', 3) == b'---'
  with fs.open('note.md', 'rb') as handle:
    assert handle.read() == text
  fs.pipe_file('written.md', b'---\ntitle: Written\n---\nText')
  assert (tmp_path / 'written.md').read_bytes() == b'---\ntitle: Written\n---\nText'
  assert fs.info('written.md')['gppu']['markdown']['title'] == 'Written'


def test_an_archive_member_reads_its_bytes_and_refuses_a_write(tmp_path):
  content = b'---\ntitle: Inside archive\n---\nText'
  with zipfile.ZipFile(tmp_path / 'bundle.zip', 'w') as archive:
    archive.writestr('inside/note.md', content)
  fs = GppuFileSystem(tmp_path)
  note = fs.ls('bundle.zip', recurse=True)[1]
  assert fs.cat_file(note['name']) == content
  with pytest.raises(ValueError, match='read-only'):
    fs.pipe_file(note['name'], b'no')


def test_a_row_the_index_has_dropped_is_not_read_as_unlocated(tmp_path):
  """`_unlocated` asks the index about one entry; the index can hold nothing for it."""
  (tmp_path / 'note.md').write_text('Text', encoding='utf-8')
  fs = GppuFileSystem(tmp_path, locations={tmp_path.as_posix(): {'location': 'work', 'canonical': 'work://'}})
  assert fs.ls()[0]['gppu']['location']['address'] == 'work://note.md'
  fs._forget('note.md')
  assert fs._unlocated('note.md') is False


def test_a_location_address_is_an_address_gppufs_answers_to(tmp_path):
  """The permalink is on every row the location handler identifies, so asking for it back must reach the entry."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'note.md').write_bytes(b'---\ntitle: Permalink\n---\nText')
  fs = GppuFileSystem(tmp_path, locations={tmp_path.as_posix(): {'location': 'perma', 'canonical': 'perma://Test'}})
  assert [row['gppu']['location']['address'] for row in fs.ls(recurse=True)] == \
         ['perma://Test/notes', 'perma://Test/notes/note.md']
  assert fs.info('perma://Test/notes/note.md')['gppu']['markdown']['title'] == 'Permalink'
  assert fs.cat_file('perma://Test/notes/note.md') == b'---\ntitle: Permalink\n---\nText'
  assert fs.ls('perma://Test/notes') == fs.ls('notes')
  assert fs.info('perma://Test') == fs.info()
  with pytest.raises(ValueError, match='outside location'):
    fs.info('elsewhere://Other/note.md')


def test_the_deepest_location_address_names_the_entry(tmp_path):
  inner = tmp_path / 'inner'
  inner.mkdir()
  (inner / 'note.md').write_bytes(b'Text')
  fs = GppuFileSystem(tmp_path, locations={
    tmp_path.as_posix(): {'location': 'outer', 'canonical': 'outer://'},
    inner.as_posix(): {'location': 'inner', 'canonical': 'outer://inner-store'}})
  assert fs.info('outer://inner-store/note.md') == fs.info('inner/note.md')
  assert fs.info('outer://inner')['type'] == 'directory'


def test_a_store_that_refuses_the_index_is_still_read(tmp_path, monkeypatch):
  """Alex, 2026-09-17 03:49: "local databases are caches for runtime and original indexes ... Don't count
  on these being present". GitHub serves read-only, so the file beside the location cannot be
  written; the listing, the parsing and the reading all still answer."""

  def refuse(*args, **kwargs):
    raise NotImplementedError

  native = MemoryFileSystem()
  root = '/' + tmp_path.name + '-readonly'
  native.makedirs(root)
  native.pipe_file(root + '/note.md', b'---\ntitle: Read only\n---\nText')
  monkeypatch.setattr(MemoryFileSystem, 'pipe_file', refuse)
  fs = GppuFileSystem('memory://' + root)
  rows = fs.ls()
  assert [row['gppu']['name'] for row in rows] == ['note.md']
  assert rows[0]['gppu']['markdown']['title'] == 'Read only'
  assert fs._cacheless is True
  assert not native.exists(root + '/.' + tmp_path.name + '-readonly.gppufs.sqlite')
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert fs.ls() == rows


def test_a_folder_that_cannot_hold_the_index_is_still_listed(tmp_path):
  """Alex, 2026-09-17 03:49: "Don't count on these being present". The index beside a location is a
  cache, so a folder that will not take the file is listed live through the handlers instead of
  raising `unable to open database file` on every read path."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'note.md').write_bytes(b'---\ntitle: No cache\n---\nText')
  index(tmp_path).mkdir()                      # a directory where the database would go
  fs = GppuFileSystem(tmp_path)
  rows = fs.ls(recurse=True)
  assert [row['gppu']['name'] for row in rows] == ['notes', 'note.md']
  assert fs.info('notes/note.md')['gppu']['markdown']['title'] == 'No cache'
  assert fs.cat_file('notes/note.md') == b'---\ntitle: No cache\n---\nText'
  assert fs._cacheless is True
  assert index(tmp_path).is_dir(), 'nothing may be written where the cache cannot go'


class Remembering:
  """An index that answers from what it was given, and records every lookup and every write."""

  def __init__(self) -> None:
    self.held: dict[str, tuple[dict | None, list | None]] = {}
    self.asked: list[str] = []

  def entry(self, address):
    self.asked.append(address)
    return self.held.get(address)

  def put(self, entries):
    for address, (metadata, children) in entries.items():
      before = self.held.get(address, (None, None))
      self.held[address] = (metadata if metadata is not None else before[0],
                            children if children is not None else before[1])


def test_the_index_answers_first_and_the_handler_runs_for_what_it_lacks(tmp_path, monkeypatch):
  """Alex, 2026-09-17 03:45: "If metadata is already in database - handler is not involved"."""
  (tmp_path / 'note.md').write_bytes(b'---\ntitle: Indexed\n---\nText')
  index = Remembering()
  fs = GppuFileSystem(tmp_path, index=index)
  rows = fs.ls()
  assert [row['gppu']['name'] for row in rows] == ['note.md']
  assert fs.info('note.md')['gppu']['markdown']['title'] == 'Indexed'
  assert index.asked, 'the index is asked'
  assert any(address.endswith('/note.md') for address in index.held), 'what the handler read is kept'

  # A second filesystem, handed the same index, must not run a handler for what the index holds.
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  monkeypatch.setattr(GppuFileSystem, '_identify_entry', no_live)
  again = GppuFileSystem(tmp_path, index=index)
  assert [row['gppu']['name'] for row in again.ls()] == ['note.md']
  assert again.info('note.md')['gppu']['markdown']['title'] == 'Indexed'
  assert again.info()['gppu']['name'] == tmp_path.name


class Empty:
  """An index that holds nothing, so every lookup falls to what is beside the location."""

  def entry(self, address):
    return None

  def put(self, entries):
    pass


def test_the_file_beside_a_location_is_kept_and_answers_when_the_index_has_nothing(tmp_path, monkeypatch):
  """Alex, 2026-09-17 04:47: the index beside a folder is not a throwaway. It is written wherever the
  place will hold it, and a folder the database has nothing for is answered from it rather than read
  again — which is how a folder archived a year ago is still known without opening what is in it."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'note.md').write_bytes(b'---\ntitle: Kept\n---\nText')
  fs = GppuFileSystem(tmp_path)
  rows = fs.ls(recurse=True)
  assert index(tmp_path).is_file(), 'a writable folder keeps its index'
  assert index(tmp_path).stat().st_size > 0

  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  monkeypatch.setattr(GppuFileSystem, '_identify_entry', no_live)
  again = GppuFileSystem(tmp_path, index=Empty())
  assert again.ls(recurse=True) == rows


class Watching(Remembering):
  """An index that also records the moves it is told about."""

  def __init__(self) -> None:
    super().__init__()
    self.moves: list[tuple[str, str]] = []

  def moved(self, source, destination):
    self.moves.append((source, destination))
    held = self.held.pop(source, None)
    if held is not None:
      self.held[destination] = held


def test_a_move_carries_what_is_held_of_the_thing_moved(tmp_path):
  """Alex's reason for a file manager on this filesystem: a folder moved between two indexed places
  keeps its index, so what was said about a file survives the move instead of being read again."""
  (tmp_path / 'a').mkdir()
  (tmp_path / 'b').mkdir()
  (tmp_path / 'a' / 'note.md').write_bytes(b'---\ntitle: Moved\n---\nText')
  watching = Watching()
  fs = GppuFileSystem(tmp_path, locations={tmp_path.as_posix(): {'location': 'work', 'canonical': 'work://'}},
                      index=watching)
  fs.ls(recurse=True)
  assert fs.info('a/note.md')['gppu']['markdown']['title'] == 'Moved'

  fs.mv('a/note.md', 'b/note.md')
  assert (tmp_path / 'b' / 'note.md').is_file()
  assert not (tmp_path / 'a' / 'note.md').exists()
  assert watching.moves == [('work://a/note.md', 'work://b/note.md')]

  # Nothing is read again: the row that was there is the row that is here.
  fs._live = no_live
  fs._identify_entry = no_live
  assert fs.info('b/note.md')['gppu']['markdown']['title'] == 'Moved'
  assert [row['gppu']['name'] for row in fs.ls('b')] == ['note.md']


class Carrying(Watching):
  """An index that carries an entry and everything under it when it is told the thing moved."""

  def moved(self, source, destination):
    self.moves.append((source, destination))
    def carried(address):
      return destination + address[len(source):] if address == source or address.startswith(source + '/') else address
    for address in [held for held in self.held if held == source or held.startswith(source + '/')]:
      row, children = self.held.pop(address)
      self.held[carried(address)] = (
        row, None if children is None else [{**child, 'path': carried(child['path'])} for child in children])


def test_a_folder_moved_between_two_locations_keeps_its_index(tmp_path):
  """Alex's headline case for the file manager: a folder carried between two indexed places, where
  what the index says about it goes with it rather than being read again."""
  one, two = tmp_path / 'SD.agents', tmp_path / 'SD.Lake'
  (one / 'work').mkdir(parents=True)
  two.mkdir()
  (one / 'work' / 'note.md').write_bytes(b'---\ntitle: Carried\n---\nText')
  locations = {one.as_posix(): {'location': 'a', 'canonical': 'a://'},
               two.as_posix(): {'location': 'b', 'canonical': 'b://'}}
  carrying = Carrying()
  source = GppuFileSystem(one, locations=locations, index=carrying)
  destination = GppuFileSystem(two, locations=locations, index=carrying)
  source.ls(recurse=True)
  assert source.info('work/note.md')['gppu']['markdown']['title'] == 'Carried'

  assert source.move_into(destination, 'work', 'work') == 'b://work'
  assert (two / 'work' / 'note.md').is_file()
  assert not (one / 'work').exists()
  assert carrying.moves == [('a://work', 'b://work')]
  assert carrying.entry('b://work/note.md')[0]['gppu']['markdown']['title'] == 'Carried'
  assert carrying.entry('a://work/note.md') is None
  assert [row['gppu']['name'] for row in destination.ls(recurse=True)] == ['work', 'note.md']


def test_a_postgres_location_is_addressed_like_any_other():
  """Alex, 2026-09-17 04:21: an index of his Postgres databases, schemas and tables. They are read
  through gppufs like any other place, so a schema is a folder and a table is an entry in it."""
  from gppu.handlers import PostgresFileSystem

  with pytest.raises(ValueError, match='dsn'):
    PostgresFileSystem('pg://pg.karel.in/files')

  fs = PostgresFileSystem('pg://pg.karel.in/files', dsn='postgresql://nobody@nowhere/files')
  assert fs.root == 'pg.karel.in/files'
  assert fs._strip_protocol('pg://pg.karel.in/files/lake') == 'pg.karel.in/files/lake'
  assert fs._under('pg.karel.in/files') == ''
  assert fs._under('pg.karel.in/files/lake') == 'lake'
  assert fs._under('pg.karel.in/files/lake/entity') == 'lake/entity'
  assert fs.info('pg.karel.in/files')['type'] == 'directory'
  assert fs.info('pg.karel.in/files/lake')['type'] == 'directory'
  with pytest.raises(ValueError, match='never written'):
    fs._open('pg.karel.in/files/lake/entity', 'wb')
