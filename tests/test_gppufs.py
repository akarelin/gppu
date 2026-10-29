from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import tarfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from fsspec.implementations.memory import MemoryFileSystem

import gppu.fs
import gppu.fs.catalog
import gppu.fs.gppufs
from gppu.fs.catalog import GppuCatalog, locate, resolve
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs import _RarFileSystem


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


def anew(**options) -> GppuFileSystem:
  """gppufs made again, as a new process makes it: what it answers comes from the indexes alone."""
  GppuFileSystem.clear_instance_cache()
  gppu.fs.gppufs._INDEXES.clear()
  return GppuFileSystem(**options)


def rename(source: Path, destination: Path, boundary: Path) -> None:
  assert source.resolve().is_relative_to(boundary.resolve())
  assert destination.resolve().is_relative_to(boundary.resolve())
  source.rename(destination)


def test_live_and_sqlite_return_all_metadata(tmp_path, monkeypatch):
  folder = tmp_path / 'notes'
  folder.mkdir()
  (folder / 'note.md').write_text('---\ntitle: Handlers\nstats: user metadata\ncreated: 2026-09-01\n---\nText', encoding='utf-8')
  session(folder / 'session.jsonl')
  fs = GppuFileSystem()
  live = fs.ls(tmp_path, recurse=True, refresh=True)
  root = fs.info(tmp_path)
  assert root['gppu']['files'] == 2
  assert root['gppu']['folders'] == 1
  note = next(row for row in live if row['name'].endswith('/note.md'))
  assert note['gppu']['record']['data']['title'] == 'Handlers'
  assert note['gppu']['record']['data']['frontmatter']['stats'] == 'user metadata'
  parsed = next(row for row in live if row['name'].endswith('/session.jsonl'))
  assert parsed['gppu']['record']['uid'] == 'codex-demo'
  assert parsed['gppu']['record']['data']['turns'] == 1
  assert index(tmp_path).is_file()
  with sqlite3.connect(index(tmp_path)) as database:
    stored = database.execute("SELECT metadata FROM gppufs_entries WHERE path='notes/session.jsonl'").fetchone()[0]
    assert json.loads(stored)['gppu']['record']['uid'] == 'codex-demo'
  assert not index(folder).exists()
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  cached = GppuFileSystem()
  assert cached.ls(tmp_path, recurse=True) == live
  assert cached.info(tmp_path) == root
  assert cached.info(note['name']) == note
  assert cached.ls(tmp_path, detail=False) == [row['name'] for row in cached.ls(tmp_path)]


def test_stats_are_aggregated_in_the_index(tmp_path, monkeypatch):
  """A location's statistics are the index's aggregate: nothing is listed or read into memory, an ignored entry is not counted,
  and a location never indexed holds nothing and is given no index."""
  folder = tmp_path / 'notes'
  folder.mkdir()
  (folder / 'note.md').write_text('Text', encoding='utf-8')
  session(folder / 'session.jsonl')
  (tmp_path / 'added.txt').write_text('added')
  (tmp_path / '.DS_Store').write_bytes(b'ignored')
  fs = GppuFileSystem()
  fs.ls(tmp_path, recurse=True)
  monkeypatch.setattr(GppuFileSystem, '_listing', no_live)
  stats = fs.stats(tmp_path)
  assert (stats['folders'], stats['files'], stats['notes'], stats['sessions']) == (1, 3, 1, 1)
  assert stats['bytes'] == sum(path.stat().st_size for path in (folder / 'note.md', folder / 'session.jsonl', tmp_path / 'added.txt'))
  assert stats['first'] <= stats['last'] and stats['seen'] is None
  empty = tmp_path.parent / f'{tmp_path.name}-empty'
  empty.mkdir()
  assert GppuFileSystem().stats(empty) == dict(folders=0, files=0, bytes=0, notes=0, sessions=0, first=None, last=None, seen=None)
  assert not index(empty).exists()


def test_an_index_past_the_limit_splits_off_the_folder_holding_most_of_it(tmp_path, monkeypatch):
  """No index grows past INDEX_LIMIT (Alex's proposal of 2026-10-21): the folder below holding the most of an index gets
  one of its own, again further down, until only one folder's own entries are left; listings and statistics stay what
  they were, and a new instance reads them from the indexes alone."""
  for name, count in (('big', 40), ('small', 2)):
    (tmp_path / name / 'deep').mkdir(parents=True)
    for i in range(count):
      (tmp_path / name / 'deep' / f'note{i}.md').write_text(f'Text {i}', encoding='utf-8')
  monkeypatch.setattr(gppu.fs.gppufs, 'INDEX_LIMIT', 32 * 1024)   # above what an index holding small's notes takes after big moves out (6 pages), below big/deep's (13)
  fs = GppuFileSystem()
  listed = fs.ls(tmp_path, recurse=True)
  assert index(tmp_path / 'big').is_file() and index(tmp_path / 'big' / 'deep').is_file()
  assert not index(tmp_path / 'small').exists() and not index(tmp_path / 'small' / 'deep').exists()
  assert index(tmp_path).stat().st_size <= gppu.fs.gppufs.INDEX_LIMIT
  assert index(tmp_path / 'big').stat().st_size <= gppu.fs.gppufs.INDEX_LIMIT
  stats = fs.stats(tmp_path)
  assert (stats['folders'], stats['files'], stats['notes']) == (4, 42, 42)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert GppuFileSystem().ls(tmp_path, recurse=True) == listed
  assert GppuFileSystem().stats(tmp_path) == stats
  monkeypatch.undo()
  with closing(sqlite3.connect(index(tmp_path))) as database, database:   # rows of big left in the root's index, as an index made before rule one has
    assert database.execute("SELECT count(*) FROM gppufs_entries WHERE path LIKE 'big%'").fetchone()[0] == 0
    database.execute('INSERT INTO gppufs_entries VALUES (?, ?, ?)', ('big/stale.md', json.dumps(listed[0]), None))
  (tmp_path / 'small' / 'added.md').write_text('More', encoding='utf-8')
  monkeypatch.setattr(gppu.fs.gppufs, 'INDEX_LIMIT', 1024)
  GppuFileSystem().ls(tmp_path / 'small')
  with closing(sqlite3.connect(index(tmp_path))) as database:   # big owns its rows in its own index: the copy is dropped, not moved
    assert database.execute("SELECT count(*) FROM gppufs_entries WHERE path LIKE 'big%'").fetchone()[0] == 0
  with closing(sqlite3.connect(index(tmp_path / 'big'))) as database:
    assert database.execute("SELECT count(*) FROM gppufs_entries WHERE path LIKE '%stale%'").fetchone()[0] == 0


def test_a_run_puts_its_indexes_into_their_folders_when_it_ends(tmp_path):
  """An index is replaced whole, never written in place (Alex's proposal of 2026-10-21): during a run the index in the
  folder is not touched, and the run's ending, however it ends, puts it there whole."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'note.md').write_text('Text', encoding='utf-8')
  fs = GppuFileSystem()
  with fs.run():
    fs.ls(tmp_path, recurse=True)
    assert not index(tmp_path).exists()
    assert [row['gppu']['name'] for row in fs.ls(tmp_path, recurse=True, live=False)] == ['notes', 'note.md']
  before = index(tmp_path).read_bytes()
  (tmp_path / 'notes' / 'added.md').write_text('More', encoding='utf-8')
  with pytest.raises(KeyboardInterrupt), fs.run():
    fs.ls(tmp_path / 'notes', refresh=True)
    assert index(tmp_path).read_bytes() == before
    raise KeyboardInterrupt
  assert [row['gppu']['name'] for row in GppuFileSystem().ls(tmp_path / 'notes', live=False)] == ['added.md', 'note.md']


def test_ls_identifies_without_probing_and_refresh_probes(tmp_path, monkeypatch):
  folder = tmp_path / 'notes'
  folder.mkdir()
  (folder / 'note.md').write_text('---\ntitle: Handlers\n---\nText', encoding='utf-8')
  fs = GppuFileSystem()
  root = fs.info(tmp_path)
  assert root['gppu']['probed'] is False
  assert root['gppu']['files'] is None
  assert index(tmp_path).is_file()
  listed = fs.ls(tmp_path, recurse=True)
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
  assert [row['gppu']['name'] for row in fs.ls(tmp_path)] == ['notes', 'added.txt']
  assert note['gppu']['probed_at'] is None
  detail = fs.info(note['name'], refresh=True)
  assert detail['gppu']['probed'] is True
  assert detail['gppu']['record']['data']['title'] == 'Handlers'
  assert datetime.fromisoformat(detail['gppu']['probed_at']).utcoffset() == datetime.now().astimezone().utcoffset()
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert fs.info(note['name']) == detail
  monkeypatch.undo()
  fs.ls(tmp_path, refresh=True, recurse=True)
  assert fs.info(tmp_path)['gppu']['files'] == 2
  assert fs.info(folder)['gppu']['probed'] is True


def test_ls_lists_removed_and_added_entries_and_refresh_forgets_removed(tmp_path):
  source = tmp_path / 'old.txt'
  source.write_text('old')
  fs = GppuFileSystem()
  fs.ls(tmp_path)
  source.unlink()
  (tmp_path / 'new.txt').write_text('new content')
  listed = fs.ls(tmp_path)
  assert [row['gppu']['name'] for row in listed] == ['new.txt']
  assert listed[0]['gppu']['probed'] is False
  fresh = fs.ls(tmp_path, refresh=True)
  assert [row['gppu']['name'] for row in fresh] == ['new.txt']
  assert fs.info(tmp_path)['gppu']['bytes'] == len('new content')
  with pytest.raises(FileNotFoundError):
    fs.info(source)


def test_failed_refresh_does_not_destroy_snapshot(tmp_path, monkeypatch):
  (tmp_path / 'note.txt').write_text('cached')
  fs = GppuFileSystem()
  before = fs.ls(tmp_path)
  def denied(*args, **kwargs):
    raise PermissionError('source unavailable')
  monkeypatch.setattr(fs, '_parse', denied)   # reading this host's disk, which a refresh does here
  with pytest.raises(PermissionError, match='source unavailable'):
    fs.ls(tmp_path, refresh=True)
  assert fs.ls(tmp_path) == before


@pytest.mark.parametrize('shard', [False, True])
def test_child_refresh_updates_ancestor_totals_from_cached_siblings(tmp_path, monkeypatch, shard):
  child = tmp_path / 'outer' / 'child'
  child.mkdir(parents=True)
  (child / 'old-2020-01-01.txt').write_text('old')
  sibling = tmp_path / 'sibling.txt'
  sibling.write_text('cached sibling')
  fs = GppuFileSystem()
  if shard:
    fs.ls(child)
  fs.ls(tmp_path, recurse=True, refresh=True)
  sibling_before = fs.info(sibling)
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
    assert key == child.as_posix(), 'Refresh reparsed outside the requested subtree'
    live(key)
  monkeypatch.setattr(fs, '_live', scoped_live)
  fs.ls(child, refresh=True)
  assert calls == [child.as_posix()]
  assert fs.info(sibling) == sibling_before
  for path, expected in (
    (child, (2, 1, 17)),
    (child.parent, (2, 2, 17)),
    (tmp_path, (3, 3, 31)),
  ):
    metadata = fs.info(path)['gppu']
    assert tuple(metadata[field] for field in ('files', 'folders', 'bytes')) == expected
    assert metadata['span'][0].startswith('2026-01-01')
  before = fs.info(tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert anew().info(tmp_path) == before


def test_caching_a_new_child_updates_its_cached_parent_listing(tmp_path):
  (tmp_path / 'before.txt').write_text('before')
  fs = GppuFileSystem()
  fs.ls(tmp_path)
  (tmp_path / 'added.txt').write_text('added')
  added = fs.info(tmp_path / 'added.txt', refresh=True)
  assert added['gppu']['probed'] is True
  assert [row['gppu']['name'] for row in fs.ls(tmp_path)] == ['added.txt', 'before.txt']
  assert fs.info(tmp_path)['gppu']['files'] == 2
  assert fs.info(tmp_path)['gppu']['bytes'] == 11


def test_refresh_rereads_metadata_when_size_and_mtime_are_unchanged(tmp_path):
  note = tmp_path / 'note.md'
  note.write_text('---\ntitle: Before\n---\nText', encoding='utf-8')
  fs = GppuFileSystem()
  before, = fs.ls(tmp_path)
  status = note.stat()
  note.write_text('---\ntitle: After!\n---\nText', encoding='utf-8')
  os.utime(note, ns=(status.st_atime_ns, status.st_mtime_ns))
  assert fs.ls(tmp_path) == [before]
  assert fs.info(note, refresh=True)['gppu']['record']['data']['title'] == 'After!'


@pytest.mark.parametrize('shard', [False, True])
@pytest.mark.parametrize('method', ['ls', 'info'])
def test_folder_rename_preserves_rows(tmp_path, monkeypatch, shard, method):
  outer = tmp_path / 'outer'
  outer.mkdir()
  old = outer / 'old'
  old.mkdir()
  session(old / 'session.jsonl')
  (old / 'note.md').write_text('---\npath: old/user-authored-value\n---\nText')
  fs = GppuFileSystem()
  if shard:
    fs.ls(old)
  fs.ls(tmp_path, recurse=True, refresh=True)
  before = fs.info(old / 'session.jsonl')
  new = outer / 'renamed'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  if method == 'ls':
    rows = fs.ls(outer)
    assert [row['gppu']['name'] for row in rows] == ['renamed']
  else:
    assert fs.info(new)['gppu']['name'] == 'renamed'
  after = fs.info(new / 'session.jsonl')
  assert after['ino'] == before['ino']
  assert after['gppu']['record']['uid'] == 'codex-demo'
  assert after['name'] == (new / 'session.jsonl').as_posix()
  assert fs.info(new / 'note.md')['gppu']['record']['data']['frontmatter']['path'] == 'old/user-authored-value'
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
  GppuFileSystem().ls(old, refresh=True)
  contents = index(old).read_bytes()
  new = tmp_path / 'renamed'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  fs = anew()
  assert fs.info(new)['gppu']['name'] == 'renamed'
  assert fs.ls(new)[0]['gppu']['record']['uid'] == 'codex-demo'
  assert index(new).read_bytes() == contents
  assert not (new / '.original.gppufs.sqlite').exists()


def test_location_rename_after_info_without_root_listing(tmp_path, monkeypatch):
  old = tmp_path / 'old'
  old.mkdir()
  (old / 'file.txt').write_text('cached')
  GppuFileSystem().info(old / 'file.txt')
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert anew().info(new / 'file.txt')['gppu']['bytes'] == 6
  assert index(new).is_file()


def test_refresh_renamed_folder_updates_existing_paths(tmp_path):
  old = tmp_path / 'old'
  old.mkdir()
  (old / 'file.txt').write_text('cached')
  fs = GppuFileSystem()
  fs.ls(tmp_path)
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  (new / 'file.txt').write_text('changed')
  assert fs.ls(new, refresh=True)[0]['gppu']['bytes'] == 7
  assert [row['gppu']['name'] for row in fs.ls(tmp_path)] == ['new']


def test_case_only_folder_rename_updates_index_filename(tmp_path, monkeypatch):
  old = tmp_path / 'MixedCase'
  old.mkdir()
  (old / 'file.txt').write_text('cached')
  fs = GppuFileSystem()
  fs.ls(old)
  fs.ls(tmp_path)
  new = tmp_path / 'MIXEDCASE'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert fs.ls(tmp_path)[0]['gppu']['name'] == 'MIXEDCASE'
  assert index(new).name in [path.name for path in new.iterdir()]
  assert '.MixedCase.gppufs.sqlite' not in [path.name for path in new.iterdir()]
  assert fs.ls(new)[0]['gppu']['bytes'] == 6


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
  fs = GppuFileSystem()
  rows = fs.ls(path, recurse=True)
  assert [row['gppu']['name'] for row in rows] == ['inside', 'note.md']
  folder, note = rows
  container = path.as_posix()
  assert folder['name'] == container + '/inside'
  assert note['name'] == container + '/inside/note.md'
  assert folder['gppu']['parent'] == container
  assert note['gppu']['parent'] == folder['name']
  assert all(row['gppu']['probed'] is False for row in rows)
  assert folder['gppu']['files'] is None
  assert note['gppu']['handlers'] == ['markdown']
  assert note['gppu']['bytes'] == len(content)
  assert 'markdown' not in note['gppu']
  assert fs.info(path)['gppu']['is_container']
  assert fs.info(note['gppu']['parent'])['type'] == 'directory'
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  fs = anew()
  assert fs.ls(path, recurse=True) == rows
  assert fs.ls(folder['name']) == [note]
  monkeypatch.undo()
  detail = fs.info(note['name'], refresh=True)
  assert detail['gppu']['probed'] is True
  assert detail['gppu']['record']['data']['title'] == 'Inside archive'
  assert fs.info(folder['name'])['gppu']['files'] is None
  probed = fs.ls(path, recurse=True, refresh=True)
  assert all(row['gppu']['probed'] is True for row in probed)
  assert probed[0]['gppu']['files'] == 1
  assert probed[1]['gppu']['record']['data']['title'] == 'Inside archive'
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert anew().ls(path, recurse=True) == probed


def test_nonlocal_fsspec_location_is_read_and_never_written(tmp_path, monkeypatch):
  """Only the host a location belongs to writes its indexes (Alex's proposal of 2026-10-21): a store that is not this host's
  own disk keeps what this instance read in memory and is given no index file; one already there is read."""
  native = MemoryFileSystem()
  root = '/' + tmp_path.name
  native.makedirs(root)
  native.pipe_file(root + '/note.md', b'---\ntitle: Remote\n---\nText')
  fs = GppuFileSystem(target_protocol='memory')
  assert 'title' not in fs.ls(root)[0]['gppu']['record']['data']   # a listing identifies; it fetches nothing
  before = fs.ls(root, refresh=True)
  assert before[0]['gppu']['record']['data']['title'] == 'Remote'
  assert not native.exists(root + '/.' + tmp_path.name + '.gppufs.sqlite')
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert fs.ls(root) == before
  monkeypatch.undo()
  local = tmp_path / tmp_path.name
  local.mkdir()
  (local / 'note.md').write_bytes(native.cat_file(root + '/note.md'))
  GppuFileSystem().ls(local, refresh=True)
  native.pipe_file(root + '/.' + tmp_path.name + '.gppufs.sqlite', index(local).read_bytes())
  reader = anew(target_protocol='memory')   # the store was asked for its index before this one was put there
  assert reader.ls(root, live=False)[0]['gppu']['record']['data']['title'] == 'Remote'


@pytest.mark.parametrize('extension', ['zip', 'tar.gz'])
def test_empty_archive_is_an_empty_listing(tmp_path, extension):
  path = tmp_path / ('empty.' + extension)
  if extension == 'zip':
    with zipfile.ZipFile(path, 'w'):
      pass
  else:
    with tarfile.open(path, 'w:gz'):
      pass
  assert GppuFileSystem().ls(path) == []


def test_nested_archives_retain_addresses_after_folder_rename(tmp_path, monkeypatch):
  old = tmp_path / 'old'
  old.mkdir()
  nested = io.BytesIO()
  with zipfile.ZipFile(nested, 'w') as archive:
    archive.writestr('note.md', '---\ntitle: Nested\n---\nText')
  with zipfile.ZipFile(old / 'outer.zip', 'w') as archive:
    archive.writestr('inner.zip', nested.getvalue())
  fs = GppuFileSystem()
  assert [row['gppu']['name'] for row in fs.ls(tmp_path, recurse=True)] == ['old', 'outer.zip']   # a recursion opens no archive
  fs.ls(old / 'outer.zip')
  fs.ls(old / 'outer.zip' / 'inner.zip')   # listed, each archive's listing is in the index, and a recursion enters it
  before = fs.ls(tmp_path, recurse=True)
  assert [row['gppu']['name'] for row in before] == ['old', 'outer.zip', 'inner.zip', 'note.md']
  assert [row['name'] for row in before] == [tmp_path.as_posix() + '/' + path for path in
    ('old', 'old/outer.zip', 'old/outer.zip/inner.zip', 'old/outer.zip/inner.zip/note.md')]
  assert [row['gppu']['parent'] for row in before[1:]] == [row['name'] for row in before[:-1]]
  assert before[-1]['gppu']['handlers'] == ['markdown']
  new = tmp_path / 'new'
  rename(old, new, tmp_path)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  after = fs.ls(tmp_path, recurse=True)
  assert all('/old/' not in row['name'] for row in after)
  assert [row['gppu']['name'] for row in after] == ['new', 'outer.zip', 'inner.zip', 'note.md']
  assert after[-1]['name'] == tmp_path.as_posix() + '/new/outer.zip/inner.zip/note.md'
  assert fs.cat_file(after[-1]['name']) == b'---\ntitle: Nested\n---\nText'
  monkeypatch.undo()
  assert fs.info(after[-1]['name'], refresh=True)['gppu']['record']['data']['title'] == 'Nested'


def test_rar_members_use_existing_handler(tmp_path, monkeypatch):
  try:
    executable = _RarFileSystem.executable()
  except FileNotFoundError as error:
    pytest.skip(str(error))
  folder = tmp_path / 'inside'
  folder.mkdir()
  (folder / 'note.md').write_text('---\ntitle: RAR metadata\n---\nText')
  subprocess.run([str(executable), 'a', '-idq', 'bundle.rar', 'inside'], cwd=tmp_path,
    check=True, capture_output=True)
  fs = GppuFileSystem()
  listed = fs.ls(tmp_path / 'bundle.rar', recurse=True)
  note = next(row for row in listed if row['gppu']['name'] == 'note.md')
  assert note['gppu']['handlers'] == ['markdown']
  assert note['gppu']['probed'] is False
  assert fs.info(note['name'], refresh=True)['gppu']['record']['data']['title'] == 'RAR metadata'
  after = fs.ls(tmp_path / 'bundle.rar', recurse=True)
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert anew().ls(tmp_path / 'bundle.rar', recurse=True) == after


def test_session_paths_inside_archives_are_source_uris(tmp_path):
  path = tmp_path / 'session.jsonl'
  session(path)
  with zipfile.ZipFile(tmp_path / 'sessions.zip', 'w') as archive:
    archive.writestr('session.jsonl', path.read_bytes())
  fs = GppuFileSystem()
  row, = fs.ls(tmp_path / 'sessions.zip')
  assert row['gppu']['handlers'] == ['session']
  detail = fs.info(row['name'], refresh=True)
  assert detail['name'] == tmp_path.as_posix() + '/sessions.zip/session.jsonl'
  container = fs.info(detail['gppu']['parent'])
  assert container['name'] == tmp_path.as_posix() + '/sessions.zip'
  assert container['gppu']['is_container']
  assert container['gppu']['bytes'] == (tmp_path / 'sessions.zip').stat().st_size
  fs.ls(tmp_path / 'sessions.zip', refresh=True)
  refreshed = fs.info(tmp_path / 'sessions.zip')
  assert refreshed['gppu']['files'] == 1
  assert refreshed['gppu']['bytes'] == container['gppu']['bytes']


@pytest.mark.parametrize('provider', ['file', 'memory'])
def test_nested_archive_uris_read_without_prior_listing(tmp_path, provider):
  content = b'---\ntitle: Nested direct read\n---\nText'
  inner, outer = io.BytesIO(), io.BytesIO()
  with zipfile.ZipFile(inner, 'w') as archive:
    archive.writestr('notes/note.md', content)
  with zipfile.ZipFile(outer, 'w') as archive:
    archive.writestr('inside/inner.zip', inner.getvalue())
  if provider == 'file':
    (tmp_path / 'outer.zip').write_bytes(outer.getvalue())
    fs, root = GppuFileSystem(), tmp_path.as_posix()
  else:
    native = MemoryFileSystem()
    root = '/' + tmp_path.name
    native.makedirs(root)
    native.pipe_file(root + '/outer.zip', outer.getvalue())
    fs = GppuFileSystem(target_protocol='memory')
  uri = root + '/outer.zip/inside/inner.zip/notes/note.md'
  assert fs.cat_file(uri) == content
  assert fs.cat_file(root + '/outer.zip/inside/inner.zip') == inner.getvalue()
  assert fs.info(uri)['gppu']['handlers'] == ['markdown']   # identified from its archives' listings, nothing read
  detail = fs.info(uri, refresh=True)
  assert detail['name'] == uri
  assert detail['gppu']['record']['data']['title'] == 'Nested direct read'
  assert fs.info(detail['gppu']['parent'])['name'] == uri.rsplit('/', 1)[0]
  assert fs.ls(uri.rsplit('/', 1)[0], detail=False) == [uri]


def test_an_archive_is_listed_by_its_own_path(tmp_path):
  path = tmp_path / 'root.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('note.md', 'Text')
  fs = GppuFileSystem()
  row, = fs.ls(path)
  assert row['name'] == path.as_posix() + '/note.md'
  assert row['gppu']['parent'] == path.as_posix()
  assert fs.info(path)['gppu']['is_container']
  assert fs.cat_file(row['name']) == b'Text'


def test_a_folder_named_zip_remains_a_folder(tmp_path):
  folder = tmp_path / 'notes.zip'
  folder.mkdir()
  (folder / 'note.txt').write_bytes(b'Text')
  fs = GppuFileSystem()
  assert fs.info(folder)['type'] == 'directory'
  assert fs.ls(folder, detail=False) == [folder.as_posix() + '/note.txt']
  assert fs.cat_file(folder.as_posix() + '/note.txt') == b'Text'


def test_archive_refresh_replaces_members_at_the_same_container_uri(tmp_path):
  path = tmp_path / 'notes.zip'
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('old.md', '---\ntitle: Old\n---\nText')
  fs = GppuFileSystem()
  fs.ls(tmp_path, refresh=True)
  old, = fs.ls(path, detail=False)
  with zipfile.ZipFile(path, 'w') as archive:
    archive.writestr('one.md', '---\ntitle: One\n---\nText')
    archive.writestr('two.md', '---\ntitle: Two\n---\nText')
  rows = fs.ls(path, refresh=True)
  assert [row['name'] for row in rows] == [path.as_posix() + '/' + name for name in ('one.md', 'two.md')]
  assert [row['gppu']['record']['data']['title'] for row in rows] == ['One', 'Two']
  assert {row['gppu']['parent'] for row in rows} == {path.as_posix()}
  assert fs.info(tmp_path)['gppu']['files'] == 1
  assert fs.info(tmp_path)['gppu']['bytes'] == path.stat().st_size
  with pytest.raises(FileNotFoundError):
    fs.info(old)


@pytest.mark.parametrize('location', ['.', 'folder'])
def test_a_relative_path_is_read_from_the_working_directory(tmp_path, monkeypatch, location):
  """A relative path names what is below the working directory, as fsspec reads it."""
  (tmp_path / 'folder').mkdir()
  (tmp_path / 'folder' / 'note.md').write_text('Text', encoding='utf-8')
  monkeypatch.chdir(tmp_path)
  fs = GppuFileSystem()
  assert fs.info(location)['name'] == (tmp_path / location).as_posix()
  assert fs.ls(location) == fs.ls(tmp_path / location)


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
  rows = GppuFileSystem().ls(tmp_path)
  assert [row['gppu']['name'] for row in rows] == ['System Volume Information', 'open.txt']
  with pytest.raises(PermissionError):
    GppuFileSystem().ls(locked)


def test_parent_traversal_is_refused(tmp_path):
  fs = GppuFileSystem()
  for path in ('../outside', tmp_path.as_posix() + '/../outside', str(tmp_path / '..' / 'outside')):
    with pytest.raises(ValueError, match='parent traversal'):
      fs.info(path)


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


def test_catalog_routes_archive_container_uris_to_the_location(tmp_path):
  root = tmp_path / 'source'
  root.mkdir()
  with zipfile.ZipFile(root / 'notes.zip', 'w') as archive:
    archive.writestr('note.md', '---\ntitle: Through catalog\n---\nText')
  catalog = GppuCatalog(catalog_of(tmp_path, [location_row(1, root)]), host='test-host')
  location, = catalog.ls()
  container_uri = location['name'] + '/notes.zip'
  row, = catalog.ls(container_uri)
  assert row['name'] == container_uri + '/note.md'
  assert row['gppu']['parent'] == container_uri
  assert catalog.info(row['name'], refresh=True)['gppu']['record']['data']['title'] == 'Through catalog'
  assert catalog.info(container_uri)['gppu']['is_container']


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
  fs = GppuFileSystem()
  assert fs._intrans is False
  assert fs._transaction is None
  assert fs.dircache is not None


def test_a_located_file_is_read_and_written_through_the_fsspec_surface(tmp_path):
  text = b'---\ntitle: Read me\n---\nText'
  note, written = tmp_path / 'note.md', tmp_path / 'written.md'
  note.write_bytes(text)
  fs = GppuFileSystem()
  assert fs.info(note, refresh=True)['gppu']['record']['data']['title'] == 'Read me'
  assert fs.cat_file(note) == text
  assert fs.head(note, 3) == b'---'
  with fs.open(note, 'rb') as handle:
    assert handle.read() == text
  fs.pipe_file(written, b'---\ntitle: Written\n---\nText')
  assert written.read_bytes() == b'---\ntitle: Written\n---\nText'
  assert fs.info(written, refresh=True)['gppu']['record']['data']['title'] == 'Written'


def test_an_archive_member_reads_its_bytes_and_refuses_a_write(tmp_path):
  content = b'---\ntitle: Inside archive\n---\nText'
  with zipfile.ZipFile(tmp_path / 'bundle.zip', 'w') as archive:
    archive.writestr('inside/note.md', content)
  fs = GppuFileSystem()
  note = fs.ls(tmp_path / 'bundle.zip', recurse=True)[1]
  assert fs.cat_file(note['name']) == content
  with pytest.raises(ValueError, match='read-only'):
    fs.pipe_file(note['name'], b'no')


def test_info_identifies_again_a_row_from_before_the_location(tmp_path):
  """A folder indexed before the configuration named its location answers with the location, the folder itself as its children."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'note.md').write_text('Text', encoding='utf-8')
  fs = GppuFileSystem()
  fs.ls(tmp_path, recurse=True)
  folders = {tmp_path.as_posix(): {'location': 'work', 'canonical': 'work://'}}
  assert locate(folders, fs.info(tmp_path))['gppu']['location']['address'] == 'work://'
  assert locate(folders, fs.info(tmp_path / 'notes'))['gppu']['location']['address'] == 'work://notes'
  assert [locate(folders, row)['gppu']['location']['address'] for row in fs.ls(tmp_path, recurse=True)] == \
         ['work://notes', 'work://notes/note.md']


def test_an_ignored_file_is_neither_indexed_nor_listed(tmp_path):
  """An ignored file is left out of the index and of listings, parsed or not, and one an earlier listing indexed is
  dropped; info still says what it is. An ignored folder is listed and not entered."""
  (tmp_path / 'note.md').write_text('Text', encoding='utf-8')
  (tmp_path / '.DS_Store').write_bytes(b'\0')
  (tmp_path / '__pycache__').mkdir()
  (tmp_path / '__pycache__' / 'x.pyc').write_bytes(b'\0')
  fs = GppuFileSystem()
  assert [row['gppu']['name'] for row in fs.ls(tmp_path, recurse=True)] == ['__pycache__', 'note.md']
  assert [row['gppu']['name'] for row in fs.ls(tmp_path, refresh=True)] == ['__pycache__', 'note.md']
  path = tmp_path / '.DS_Store'
  assert fs.info(path)['gppu']['handlers'] == ['ignored']
  assert fs.info(path, refresh=True)['gppu']['handlers'] == ['ignored']
  assert fs.stored(path) is None
  earlier = fs._row(path.as_posix(), fs.fs.info(str(path)), gppu.fs.handlers.probe(path), path)
  fs._store(tmp_path.as_posix(), {path.as_posix(): (earlier, None)},
            fs.stored(tmp_path)[1] + [{'path': path.as_posix(), 'type': 'file', 'ino': None}])
  assert fs.stored(path) is not None
  assert [row['gppu']['name'] for row in fs.ls(tmp_path)] == ['__pycache__', 'note.md']
  assert fs.stored(path) is None
  with sqlite3.connect(index(tmp_path)) as database:
    assert {row[0] for row in database.execute('SELECT path FROM gppufs_entries')} == {'.', '__pycache__', 'note.md'}


def test_a_folder_is_asked_once_whether_it_holds_an_index(tmp_path, monkeypatch):
  """On a share every ask is a round trip: a folder is asked once in a process whether it holds an index, not again for
  each entry below it, and a folder is resolved once for the location map, not for each entry in it."""
  deep = tmp_path / 'a' / 'b'
  deep.mkdir(parents=True)
  for name in ('one.md', 'two.md'):
    (deep / name).write_text('Text', encoding='utf-8')
  asked, resolved = [], []
  index_at, full_path = GppuFileSystem._index_at, gppu.fs.catalog.full_path
  monkeypatch.setattr(GppuFileSystem, '_index_at', lambda self, folder: asked.append(folder) or index_at(self, folder))
  monkeypatch.setattr(gppu.fs.catalog, 'full_path', lambda path, *args, **kwargs: resolved.append(path) or full_path(path, *args, **kwargs))
  gppu.fs.catalog._on_host.cache_clear()
  folders = {tmp_path.as_posix(): {'location': 'work', 'canonical': 'work://'}}
  fs = GppuFileSystem()
  rows = [locate(folders, row) for row in fs.ls(tmp_path, recurse=True)]
  fs.info(deep / 'one.md')
  assert len(asked) == len(set(asked)) and len(resolved) == len(set(resolved)) < len(rows)
  asked.clear()
  resolved.clear()
  [locate(folders, row) for row in fs.ls(tmp_path, recurse=True)]
  assert locate(folders, fs.info(deep / 'one.md'))['gppu']['location']['address'] == 'work://a/b/one.md'
  assert asked == [] and resolved == []


def test_a_location_address_is_an_address_gppufs_answers_to(tmp_path):
  """The permalink is on every row the location handler identifies, so asking for it back must reach the entry."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'note.md').write_bytes(b'---\ntitle: Permalink\n---\nText')
  folders = {tmp_path.as_posix(): {'location': 'perma', 'canonical': 'perma://Test'}}
  fs = GppuFileSystem()
  assert [locate(folders, row)['gppu']['location']['address'] for row in fs.ls(tmp_path, recurse=True)] == \
         ['perma://Test/notes', 'perma://Test/notes/note.md']
  assert fs.info(resolve(folders, 'perma://Test/notes/note.md'), refresh=True)['gppu']['record']['data']['title'] == 'Permalink'
  assert fs.cat_file(resolve(folders, 'perma://Test/notes/note.md')) == b'---\ntitle: Permalink\n---\nText'
  assert fs.ls(resolve(folders, 'perma://Test/notes')) == fs.ls(tmp_path / 'notes')
  assert fs.info(resolve(folders, 'perma://Test')) == fs.info(tmp_path)
  assert resolve(folders, 'elsewhere://Other/note.md') == 'elsewhere://Other/note.md'


def test_the_deepest_location_address_names_the_entry(tmp_path):
  inner = tmp_path / 'inner'
  inner.mkdir()
  (inner / 'note.md').write_bytes(b'Text')
  folders = {tmp_path.as_posix(): {'location': 'outer', 'canonical': 'outer://'},
             inner.as_posix(): {'location': 'inner', 'canonical': 'outer://inner-store'}}
  fs = GppuFileSystem()
  assert fs.info(resolve(folders, 'outer://inner-store/note.md')) == fs.info(inner / 'note.md')
  assert fs.info(resolve(folders, 'outer://inner'))['type'] == 'directory'
  assert locate(folders, fs.info(inner / 'note.md'))['gppu']['location']['address'] == 'outer://inner-store/note.md'


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
  fs = GppuFileSystem(target_protocol='memory')
  rows = fs.ls(root, refresh=True)
  assert [row['gppu']['name'] for row in rows] == ['note.md']
  assert rows[0]['gppu']['record']['data']['title'] == 'Read only'
  assert not native.exists(root + '/.' + tmp_path.name + '-readonly.gppufs.sqlite')
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  assert fs.ls(root) == rows


def test_a_folder_that_cannot_hold_the_index_is_still_listed(tmp_path):
  """Alex, 2026-09-17 03:49: "Don't count on these being present". The index beside a location is a
  cache, so a folder that will not take the file is listed live through the handlers instead of
  raising `unable to open database file` on every read path."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'note.md').write_bytes(b'---\ntitle: No cache\n---\nText')
  index(tmp_path).mkdir()                      # a directory where the database would go
  fs = GppuFileSystem()
  rows = fs.ls(tmp_path, recurse=True)
  assert [row['gppu']['name'] for row in rows] == ['notes', 'note.md']
  note = tmp_path / 'notes' / 'note.md'
  assert fs.info(note, refresh=True)['gppu']['record']['data']['title'] == 'No cache'
  assert fs.cat_file(note) == b'---\ntitle: No cache\n---\nText'
  assert index(tmp_path).is_dir(), 'nothing may be written where the cache cannot go'


def test_archive_members_use_the_same_location_addresses_in_the_index(tmp_path, monkeypatch):
  with zipfile.ZipFile(tmp_path / 'notes.zip', 'w') as archive:
    archive.writestr('note.md', '---\ntitle: Indexed member\n---\nText')
  folders = {tmp_path.as_posix(): {'location': 'work', 'canonical': 'work://'}}
  fs = GppuFileSystem()
  row, = fs.ls(resolve(folders, 'work://notes.zip'))
  assert row['name'] == tmp_path.as_posix() + '/notes.zip/note.md'
  assert locate(folders, row)['gppu']['location']['address'] == 'work://notes.zip/note.md'
  assert fs.info(resolve(folders, 'work://notes.zip/note.md'), refresh=True)['gppu']['record']['data']['title'] == 'Indexed member'
  with sqlite3.connect(index(tmp_path)) as database:
    assert {row[0] for row in database.execute('SELECT path FROM gppufs_entries')} == {
      'notes.zip', 'notes.zip/note.md'}
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  monkeypatch.setattr(GppuFileSystem, '_identify_members', no_live)
  again = anew()
  assert again.ls(resolve(folders, 'work://notes.zip'), detail=False, live=False) == [row['name']]
  assert again.info(resolve(folders, 'work://notes.zip/note.md'))['gppu']['record']['data']['title'] == 'Indexed member'


def test_a_move_carries_what_is_held_of_the_thing_moved(tmp_path):
  """Alex's reason for a file manager on this filesystem: a folder moved between two indexed places
  keeps its index, so what was said about a file survives the move instead of being read again."""
  (tmp_path / 'a').mkdir()
  (tmp_path / 'b').mkdir()
  (tmp_path / 'a' / 'note.md').write_bytes(b'---\ntitle: Moved\n---\nText')
  fs = GppuFileSystem()
  fs.ls(tmp_path, recurse=True)
  assert fs.info(tmp_path / 'a' / 'note.md', refresh=True)['gppu']['record']['data']['title'] == 'Moved'

  fs.mv(tmp_path / 'a' / 'note.md', tmp_path / 'b' / 'note.md')
  assert (tmp_path / 'b' / 'note.md').is_file()
  assert not (tmp_path / 'a' / 'note.md').exists()

  # Nothing is read again: the row that was there is the row that is here.
  fs._live = no_live
  fs._identify_entry = no_live
  assert fs.info(tmp_path / 'b' / 'note.md')['gppu']['record']['data']['title'] == 'Moved'
  assert [row['gppu']['name'] for row in fs.ls(tmp_path / 'b')] == ['note.md']
  assert fs.stored(tmp_path / 'a' / 'note.md') is None


def test_every_row_carries_its_files_id_through_a_refresh_a_change_and_a_move(tmp_path):
  """Inside gppufs a file is its id, fs.files' kind: given when its row is first written and kept while it is read again,
  changed or moved; the path tells gppufs where it is."""
  (tmp_path / 'a').mkdir()
  (tmp_path / 'a' / 'note.md').write_text('# note')
  fs = GppuFileSystem()
  ids = {row['name']: row['gppu']['id'] for row in fs.ls(tmp_path / 'a')}
  note = ids[(tmp_path / 'a' / 'note.md').as_posix()]
  assert UUID(note).bytes[:3] == bytes([0x10, 0x02, 1])
  fs.ls(tmp_path, refresh=True)
  (tmp_path / 'a' / 'note.md').write_text('# note, changed')
  fs.ls(tmp_path / 'a', refresh=True)
  assert fs.info(tmp_path / 'a' / 'note.md')['gppu']['id'] == note
  fs.mv(tmp_path / 'a', tmp_path / 'b')
  assert fs.info(tmp_path / 'b' / 'note.md')['gppu']['id'] == note


def test_an_index_written_before_rows_carried_ids_gives_each_one_at_its_next_write(tmp_path):
  (tmp_path / 'note.md').write_text('# note')
  fs = GppuFileSystem()
  fs.ls(tmp_path)
  with closing(sqlite3.connect(index(tmp_path))) as database, database:
    database.execute("UPDATE gppufs_entries SET metadata=json_remove(metadata, '$.gppu.id')")
    database.execute('PRAGMA user_version = 0')
  GppuFileSystem.clear_instance_cache()
  gppu.fs.gppufs._INDEXES.clear()
  (tmp_path / 'later.md').write_text('# later')
  assert all(UUID(row['gppu']['id']) for row in GppuFileSystem().ls(tmp_path))


def test_a_folder_moved_between_two_locations_keeps_its_index(tmp_path, monkeypatch):
  """Alex's headline case for the file manager: a folder carried between two indexed places, where
  what the index says about it goes with it rather than being read again: the folder's own index."""
  one, two = tmp_path / 'SD.agents', tmp_path / 'SD.Lake'
  (one / 'work').mkdir(parents=True)
  two.mkdir()
  (one / 'work' / 'note.md').write_bytes(b'---\ntitle: Carried\n---\nText')
  fs = GppuFileSystem()
  fs.ls(one, recurse=True)
  fs.ls(two)
  fs.split(one / 'work')
  assert fs.info(one / 'work' / 'note.md', refresh=True)['gppu']['record']['data']['title'] == 'Carried'

  fs.makedirs(two, exist_ok=True)
  fs.mv(one / 'work', two / 'work', recursive=True)
  assert (two / 'work' / 'note.md').is_file()
  assert not (one / 'work').exists()
  monkeypatch.setattr(GppuFileSystem, '_live', no_live)
  monkeypatch.setattr(GppuFileSystem, '_identify_entry', no_live)
  assert fs.info(two / 'work' / 'note.md')['gppu']['record']['data']['title'] == 'Carried'
  assert fs.stored(one / 'work' / 'note.md') is None
  monkeypatch.undo()
  assert [row['gppu']['name'] for row in fs.ls(two, recurse=True)] == ['work', 'note.md']


def test_a_postgres_location_is_addressed_like_any_other():
  """Alex, 2026-09-17 04:21: an index of his Postgres databases, schemas and tables. They are read
  through gppufs like any other place, so a schema is a folder and a table is an entry in it."""
  from gppu.fs.gppufs import PostgresFileSystem

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


def test_a_folder_read_from_its_index_alone_keeps_what_is_no_longer_there(tmp_path):
  """Alex, 2026-09-17 04:47: an archived folder keeps its sqlite, and a folder from a year ago whose
  files are now inside a large archive is answered from that index without opening the archive;
  records of deleted files stay. Reading from the index alone is what that is."""
  (tmp_path / 'notes').mkdir()
  (tmp_path / 'notes' / 'kept.md').write_bytes(b'---\ntitle: Kept\n---\nText')
  (tmp_path / 'notes' / 'gone.md').write_bytes(b'---\ntitle: Gone\n---\nText')
  notes = tmp_path / 'notes'
  fs = GppuFileSystem()
  assert [row['gppu']['name'] for row in fs.ls(notes)] == ['gone.md', 'kept.md']
  assert fs.info(notes / 'gone.md', refresh=True)['gppu']['record']['data']['title'] == 'Gone'

  (notes / 'gone.md').unlink()        # as far as the folder knows, it is inside an archive now
  again = anew()
  assert [row['gppu']['name'] for row in again.ls(notes, live=False)] == ['gone.md', 'kept.md']
  assert again.info(notes / 'gone.md')['gppu']['record']['data']['title'] == 'Gone'

  # A folder that is still live is still read live, and there the record goes.
  assert [row['gppu']['name'] for row in again.ls(notes)] == ['kept.md']


def test_an_index_is_preserved_and_the_location_left_clean(tmp_path):
  """Alex, 2026-09-17: an index that makes a folder unclean — a repository's working tree, a library
  that will not sync a database — is preserved as a file in the lake rather than left where it is.
  The walk still writes one while it works; this is what happens at the end of it."""
  repo, lake = tmp_path / 'RAN', tmp_path / 'Lake'
  repo.mkdir()
  lake.mkdir()
  (repo / 'note.md').write_bytes(b'---\ntitle: In a repo\n---\nText')
  fs = GppuFileSystem()
  fs.ls(repo, recurse=True)
  assert index(repo).is_file(), 'the walk writes one while it works'

  kept = fs.preserve(repo, lake)
  assert kept is not None and kept.parent == lake
  assert kept.name.endswith('RAN.gppufs.sqlite') and kept.name[:6].isdigit()
  assert sorted(path.name for path in repo.iterdir()) == ['note.md'], 'the location is left clean'
  assert kept.read_bytes()
  assert fs.preserve(repo, lake) is None, 'there is nothing left to preserve'


def test_a_store_that_lists_enough_is_identified_without_its_bytes(monkeypatch):
  """A remote entry is identified by its name and its type; its bytes are never fetched to list it."""
  store = MemoryFileSystem()
  store.store.clear()
  store.pseudo_dirs.clear()
  for name, body in (('/library/notes.md', b'# notes'), ('/library/rows.csv', b'when,what' + b'\n')):
    store.pipe_file(name, body)
  store.makedirs('/library/deeper', exist_ok=True)
  monkeypatch.setattr(MemoryFileSystem, 'listing_is_enough', True, raising=False)
  def refuse(*_args, **_kwargs):
    raise AssertionError('listing a store that lists enough read its bytes')
  monkeypatch.setattr(MemoryFileSystem, 'cat_file', refuse)
  monkeypatch.setattr(MemoryFileSystem, 'get_file', refuse)

  fs = GppuFileSystem(target_protocol='memory')
  listed = {row['name'].rsplit('/', 1)[-1]: row['gppu'] for row in fs.ls('/library')}
  assert set(listed) == {'notes.md', 'rows.csv', 'deeper'}
  assert listed['notes.md']['handlers'] == ['markdown'], 'a name and a type are enough to identify'
  assert listed['rows.csv']['handlers'] == ['csv']
  assert listed['deeper']['handlers'] == ['folder']
  assert listed['notes.md']['probed'] is False, 'nothing is probed by a listing'
  assert listed['notes.md']['path'].endswith('notes.md'), 'the row names the entry, not a stand-in'
  assert listed['rows.csv']['size'] == 10, 'the size is the one the store listed'


def test_an_m365_address_names_its_tenant_service_site_and_drive():
  from gppu.fs.gppufs import SharePointFileSystem
  assert SharePointFileSystem._get_kwargs_from_urls('m365://karelin/sharepoint/sites/Suntrust/Statements') == {
    'tenant': 'karelin', 'service': 'sharepoint', 'site': 'sites/Suntrust', 'drive': 'Statements'}
  assert SharePointFileSystem._get_kwargs_from_urls('m365://karelin/onedrive/personal/alex_karelin_com/Documents') == {
    'tenant': 'karelin', 'service': 'onedrive', 'site': 'personal/alex_karelin_com', 'drive': 'Documents'}
  with pytest.raises(ValueError, match='m365://tenant/service/site/drive'):
    SharePointFileSystem._get_kwargs_from_urls('m365://karelin/sharepoint')
  with pytest.raises(ValueError, match='token'):
    SharePointFileSystem(tenant='karelin', service='sharepoint', site='sites/Suntrust', drive='Statements')


def test_an_index_in_a_repository_is_left_out_of_it(tmp_path):
  """An index written in a git work tree is in the repository's info/exclude, so git leaves it out, in a worktree too;
  the repository's .gitignore is not touched."""
  def git(*args, cwd=tmp_path / 'repo'):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout
  repo = tmp_path / 'repo'
  repo.mkdir()
  git('init', '-q')
  (repo / 'note.md').write_text('Text', encoding='utf-8')
  git('-c', 'user.name=t', '-c', 'user.email=t@t', 'add', 'note.md')
  git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'note')
  GppuFileSystem().ls(repo, recurse=True)
  assert index(repo).is_file() and git('status', '--porcelain') == ''
  assert not (repo / '.gitignore').exists()
  git('worktree', 'add', '-q', str(tmp_path / 'tree'))
  GppuFileSystem().ls(tmp_path / 'tree', recurse=True)
  assert index(tmp_path / 'tree').is_file() and git('status', '--porcelain', cwd=tmp_path / 'tree') == ''
  assert (repo / '.git' / 'info' / 'exclude').read_text(encoding='utf-8').splitlines().count(gppu.fs.gppufs.GIT_EXCLUDE) == 1
