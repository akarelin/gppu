import io
import re
import shutil
import sqlite3
import zipfile
from datetime import datetime

import pytest

from gppu.desktop import DesktopFileSystem
from gppu.fs import GppuFileSystem
from gppu.fs_index import GppuIndexedFileSystem


def test_desktop_archive_navigation_and_reads(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, 'w') as archive:
        archive.writestr('Привет #100%.txt', 'hello from the archive')
    with zipfile.ZipFile(tmp_path / 'outer.zip', 'w') as archive:
        archive.writestr('folder/inner.zip', inner.getvalue())
    (tmp_path / 'plain.txt').write_text('ordinary file')
    fs = DesktopFileSystem({'Lake': GppuFileSystem(tmp_path)})
    assert fs.ls('/', detail=False) == ['/Lake', '/Indexed']
    assert fs.info('/Lake/outer.zip')['type'] == 'directory'
    assert fs.ls('/Lake/outer.zip', detail=False) == ['/Lake/outer.zip/folder']
    assert fs.info('/Lake/outer.zip/folder/inner.zip')['type'] == 'directory'
    member = '/Lake/outer.zip/folder/inner.zip/Привет #100%.txt'
    assert fs.ls('/Lake/outer.zip/folder/inner.zip', detail=False) == [member]
    assert fs.cat_file(member) == b'hello from the archive'
    assert fs.cat_file('/lake/plain.txt') == b'ordinary file'
    with pytest.raises(OSError, match='read-only'):
        fs.open('/Lake/plain.txt', 'wb')
    assert (tmp_path / 'plain.txt').read_text() == 'ordinary file'
    with pytest.raises(ValueError, match='cannot leave'):
        fs.info('/Lake/../plain.txt')
    with pytest.raises(FileNotFoundError):
        fs.info('/missing/plain.txt')


def test_desktop_multiple_sources_and_collisions(tmp_path):
    left, right = tmp_path / 'left', tmp_path / 'right'
    left.mkdir()
    right.mkdir()
    (left / 'note.txt').write_text('left')
    (right / 'note.txt').write_text('right')
    sources = {'One': GppuFileSystem(left), 'Two': GppuFileSystem(right)}
    fs = DesktopFileSystem(sources)
    assert fs.cat_file('/One/note.txt') == b'left'
    assert fs.cat_file('/Two/note.txt') == b'right'
    with pytest.raises(ValueError, match='distinct'):
        DesktopFileSystem({'One': sources['One'], 'one': sources['Two']})


def test_unrelated_copied_index_is_preserved(tmp_path):
    original, copied = tmp_path / 'original', tmp_path / 'copied'
    original.mkdir()
    copied.mkdir()
    (original / 'note.txt').write_text('original')
    GppuFileSystem(original).ls_sync()
    old_index = copied / '.original.gppufs.sqlite'
    shutil.copyfile(original / '.original.gppufs.sqlite', old_index)
    before = old_index.read_bytes()
    with sqlite3.connect(old_index) as db:
        assert db.execute('SELECT ino FROM gppufs_index').fetchone()[0] != copied.stat().st_ino
    (copied / 'actual.txt').write_text('copied folder')
    fs = DesktopFileSystem({'Data': GppuFileSystem(tmp_path)})
    assert '/Data/copied/actual.txt' in fs.ls('/Data/copied', detail=False)
    assert old_index.read_bytes() == before
    assert not (copied / '.copied.gppufs.sqlite').exists()
    snapshot = copied / '261021 original.gppufs.sqlite'
    shutil.copyfile(old_index, snapshot)
    assert all(not name.endswith('.gppufs.sqlite') for name in fs.ls('/Data/copied', detail=False))


def test_index_view_reads_deep_entries_without_listing_source(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    folder = root / 'account' / 'year' / 'month' / 'day'
    folder.mkdir(parents=True)
    (folder / 'note.txt').write_text('deep indexed content')
    (root / 'other').mkdir()
    (root / 'other' / 'note.txt').write_text('another note')
    source = GppuFileSystem(root)
    source.ls_sync(recurse=True)
    fs = DesktopFileSystem({'Data': source})
    views = fs.ls('/Indexed', detail=False)
    assert '/Indexed/Data › source' in views
    view = '/Indexed/Data › source'
    monkeypatch.setattr(GppuFileSystem, 'ls_sync', lambda *a, **k: pytest.fail('indexed listing touched source hierarchy'))
    names = fs.ls(view, detail=False)
    assert view + '/account › year › month › day › note.txt' in names
    assert view + '/other › note.txt' in names
    assert fs.cat_file(view + '/account › year › month › day › note.txt') == b'deep indexed content'
    assert fs.cat_file(view + '/other › note.txt') == b'another note'


def test_synced_index_is_read_without_renaming_or_touching_content(tmp_path, monkeypatch):
    root = tmp_path / 'original'
    root.mkdir()
    folder = root / 'a' / 'b' / 'c'
    folder.mkdir(parents=True)
    (folder / 'note.txt').write_text('the source')
    GppuFileSystem(root).ls_sync(recurse=True)
    synced = tmp_path / 'synced'
    synced.mkdir()
    index = synced / '.original.gppufs.sqlite'
    shutil.copyfile(root / '.original.gppufs.sqlite', index)
    before = index.read_bytes()
    view = GppuIndexedFileSystem(index)
    monkeypatch.setattr(GppuFileSystem, 'ls_sync', lambda *a, **k: pytest.fail('read original hierarchy'))
    assert view.ls(detail=False) == ['/note.txt']
    assert view.info('/note.txt')['size'] == len('the source')
    with pytest.raises(FileNotFoundError):
        view.cat_file('/note.txt')
    assert index.read_bytes() == before
    assert not (synced / '.synced.gppufs.sqlite').exists()


def test_index_view_names_archive_members_for_windows_and_leaves_out_ignored(tmp_path):
    root = tmp_path / 'original'
    root.mkdir()
    (root / 'note.txt').write_text('a note')
    with zipfile.ZipFile(root / 'bundle.zip', 'w') as archive:
        archive.writestr('inner/member.txt', 'from the archive')
    GppuFileSystem(root).ls_sync()
    index = root / '.original.gppufs.sqlite'
    with sqlite3.connect(index) as db:   # rows an earlier gppufs wrote: archive members chained as fsspec chains them, an ignored file
        metadata = db.execute("SELECT metadata FROM gppufs_entries WHERE path='note.txt'").fetchone()[0]
        ignored = metadata.replace('"handlers": [', '"handlers": ["ignored", ')
        db.executemany('INSERT INTO gppufs_entries VALUES (?, ?, NULL)', [
            ('zip://inner/member.txt::bundle.zip', metadata), ('zip://gone.txt::missing.zip', metadata), ('.DS_Store', ignored)])
    view = GppuIndexedFileSystem(index)
    names = view.ls(detail=False)
    assert '/member.txt' in names and '/gone.txt' in names and '/.DS_Store' not in names
    assert not any(':' in name for name in names)
    assert view.cat_file('/member.txt') == b'from the archive'
    with pytest.raises(FileNotFoundError):
        view.cat_file('/gone.txt')


def test_a_time_an_index_holds_as_text_reaches_windows_in_seconds(tmp_path):
    root = tmp_path / 'original'
    root.mkdir()
    (root / 'note.txt').write_text('a note')
    GppuFileSystem(root).ls_sync()
    with sqlite3.connect(root / '.original.gppufs.sqlite') as db:   # an archive member's row: its time as text
        metadata = db.execute("SELECT metadata FROM gppufs_entries WHERE path='note.txt'").fetchone()[0]
        member = re.sub(r'"mtime": [0-9.]+', '"mtime": "2026-08-05 16:08:05-07:00"', metadata)
        db.execute('INSERT INTO gppufs_entries VALUES (?, ?, NULL)', ('zip://member.txt::bundle.zip', member))
    fs = DesktopFileSystem({'Data': GppuFileSystem(root)})
    view = next(name for name in fs.ls('/Indexed', detail=False) if name.endswith('original'))
    assert fs.info(view + '/member.txt')['mtime'] == datetime.fromisoformat('2026-08-05 16:08:05-07:00').timestamp()
    assert isinstance(fs.info(view + '/note.txt')['mtime'], float)


def test_a_drive_root_is_a_source(tmp_path):
    fs = DesktopFileSystem({'Data': GppuFileSystem(tmp_path.anchor)})
    assert fs.info('/Data')['type'] == 'directory'


def test_transported_snapshot_never_reads_unrelated_sibling_files(tmp_path):
    root = tmp_path / 'original'
    root.mkdir()
    (root / 'note.txt').write_text('original')
    GppuFileSystem(root).ls_sync()
    destination = tmp_path / 'destination'
    destination.mkdir()
    (destination / 'note.txt').write_text('unrelated')
    snapshot = destination / '261021 original.gppufs.sqlite'
    shutil.copyfile(root / '.original.gppufs.sqlite', snapshot)
    view = GppuIndexedFileSystem(snapshot)
    assert view.ls(detail=False) == ['/note.txt']
    with pytest.raises(FileNotFoundError, match='no bound original source'):
        view.cat_file('/note.txt')
