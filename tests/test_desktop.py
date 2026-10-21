import io
import shutil
import sqlite3
import zipfile

import pytest

from gppu.desktop import DesktopFileSystem
from gppu.fs import GppuFileSystem


def test_desktop_archive_navigation_and_reads(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, 'w') as archive:
        archive.writestr('Привет #100%.txt', 'hello from the archive')
    with zipfile.ZipFile(tmp_path / 'outer.zip', 'w') as archive:
        archive.writestr('folder/inner.zip', inner.getvalue())
    (tmp_path / 'plain.txt').write_text('ordinary file')
    fs = DesktopFileSystem({'Lake': GppuFileSystem(tmp_path)})
    assert fs.ls('/', detail=False) == ['/Lake']
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
