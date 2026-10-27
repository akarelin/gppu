import io
import os
import re
import shutil
import sqlite3
import zipfile
from datetime import datetime

import pytest

from gppu.fs.desktop import DesktopFileSystem
from gppu.fs import GppuFileSystem
from gppu.fs.fs_index import GppuIndexedFileSystem


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
    assert view + '/day › note.txt' in names   # named by the fewest folders that tell the two notes apart
    assert view + '/other › note.txt' in names
    assert fs.cat_file(view + '/day › note.txt') == b'deep indexed content'
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


def test_a_name_longer_than_windows_holds_keeps_the_end_nearest_the_file(tmp_path):
    root = tmp_path / 'original'
    root.mkdir()
    (root / 'note.txt').write_text('a note')
    GppuFileSystem(root).ls_sync()
    index = root / '.original.gppufs.sqlite'
    with sqlite3.connect(index) as db:   # two notes told apart only by folders whose names together pass 255 characters
        metadata = db.execute("SELECT metadata FROM gppufs_entries WHERE path='note.txt'").fetchone()[0]
        db.executemany('INSERT INTO gppufs_entries VALUES (?, ?, NULL)', [
            (f'{"a" * 200}/{"b" * 100}/note.txt', metadata), (f'{"c" * 200}/{"b" * 100}/note.txt', metadata)])
    names = [name.lstrip('/') for name in GppuIndexedFileSystem(index).ls(detail=False)]
    long = [name for name in names if name.startswith('…')]
    assert len(long) == 2 and all(len(name) == 255 and name.endswith('b' * 100 + ' › note.txt') for name in long)
    assert 'note.txt' in names and len(set(names)) == 3   # the note at the top has no folder to be told apart by


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


def test_a_session_is_shown_by_its_handlers_name_and_dated_by_its_span(tmp_path):
    """Rich information (SPEC_desktop's first use case): a session the handler read is shown by the name SessionHandler gives
    it, its start, turns, length and topic, and Windows' created and modified times are its span; it is found and read by
    that name, before its folder is listed too."""
    import json
    folder = tmp_path / 'sessions'
    folder.mkdir()
    lines = ({'type': 'session_meta', 'timestamp': '2026-09-01T08:00:00Z', 'payload': {'id': 'codex-demo'}},
             {'type': 'response_item', 'timestamp': '2026-09-01T08:01:00Z', 'payload': {
                 'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Show the handlers'}]}},
             {'type': 'response_item', 'timestamp': '2026-09-01T08:05:00Z', 'payload': {
                 'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Here they are'}]}})
    (folder / 'rollout.jsonl').write_text('\n'.join(json.dumps(line) for line in lines), encoding='utf-8')
    (folder / 'plain.txt').write_text('ordinary file')
    GppuFileSystem(tmp_path).ls('sessions', refresh=True)
    fs = DesktopFileSystem({'home': GppuFileSystem(tmp_path)})
    names = fs.ls('/home/sessions', detail=False)
    shown = next(name for name in names if name != '/home/sessions/plain.txt')
    assert re.fullmatch(r'/home/sessions/260901-\d{4} \d+~\d+m - Show the handlers\.codex-demo\.jsonl', shown)
    row = fs.info(shown)
    start, end = GppuFileSystem(tmp_path).info('sessions/rollout.jsonl')['gppu']['record']['span']
    assert (row['ctime'], row['mtime']) == (datetime.fromisoformat(start).timestamp(), datetime.fromisoformat(end).timestamp())
    assert row['ctime'] < row['mtime']
    assert fs.cat_file(shown) == (folder / 'rollout.jsonl').read_bytes()
    assert DesktopFileSystem({'home': GppuFileSystem(tmp_path)}).cat_file(shown) == (folder / 'rollout.jsonl').read_bytes()
    assert fs.info('/home/sessions/plain.txt')['ctime'] == pytest.approx((folder / 'plain.txt').stat().st_ctime)


def _made(root, *paths):
    for n, path in enumerate(paths):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.endswith('.zip'):
            with zipfile.ZipFile(target, 'w') as archive:
                archive.writestr('final.md', path)
        else:
            target.write_text(path)
        os.utime(target, (1_790_000_000 + n, 1_790_000_000 + n))   # each written after the one before


def test_work_shows_each_task_once_by_its_own_name(tmp_path):
    work = tmp_path / 'Work'
    _made(work, '10/21/ov-memory/plan.md', '10/22/ov-memory/plan.md', '10/22/ov-memory/run.py', '10/22/speed/record.md',
          '10/21/gppu/notes.md', '10/23/gppu.zip', '10/21/notes.md', '10/22/notes.md', 'README.md', '10/22/.git/HEAD')
    fs = DesktopFileSystem({'Work': GppuFileSystem(work)})
    assert sorted(fs.ls('/Work', detail=False)) == ['/Work/README.md', '/Work/gppu', '/Work/notes.md', '/Work/ov-memory', '/Work/speed']
    assert sorted(fs.ls('/Work/ov-memory', detail=False)) == ['/Work/ov-memory/plan.md', '/Work/ov-memory/run.py']
    assert fs.cat_file('/Work/ov-memory/plan.md') == b'10/22/ov-memory/plan.md'   # a file a task keeps on several days: its latest
    assert fs.cat_file('/Work/notes.md') == b'10/22/notes.md'
    assert sorted(fs.ls('/Work/gppu', detail=False)) == ['/Work/gppu/final.md', '/Work/gppu/notes.md']   # its archived stage too
    assert fs.cat_file('/Work/gppu/final.md') == b'10/23/gppu.zip'
    task = fs.info('/Work/ov-memory')
    assert task['type'] == 'directory' and task['mtime'] == pytest.approx(max((work / '10' / day / 'ov-memory').stat().st_mtime for day in ('21', '22')), abs=1e-3)
    with pytest.raises(IsADirectoryError):
        fs.open('/Work/ov-memory')
    fs.ls('/Work', detail=False)   # its files are in the index now: a task's span is theirs, on each day it was kept
    task = fs.info('/Work/ov-memory')
    assert (task['ctime'], task['mtime']) == (pytest.approx(1_790_000_000, abs=1e-3), pytest.approx(1_790_000_002, abs=1e-3))


def test_projects_shows_a_project_kept_over_months_once_by_its_own_name(tmp_path):
    projects = tmp_path / 'Projects'
    _made(projects, '09/2026-09 Linked Data/260920-schema/a.md', '10/2026-10 Linked Data/261018-api/b.md',
          '10/2026-10 Linked Data/261019-api.zip', '10/261005 tony-lifespan/c.md', '2026-10 Suno/d.md')
    fs = DesktopFileSystem({'Projects': GppuFileSystem(projects)})
    assert sorted(fs.ls('/Projects', detail=False)) == ['/Projects/Linked Data', '/Projects/Suno', '/Projects/tony-lifespan']
    assert sorted(fs.ls('/Projects/Linked Data', detail=False)) == ['/Projects/Linked Data/api', '/Projects/Linked Data/schema']
    assert sorted(fs.ls('/Projects/Linked Data/api', detail=False)) == ['/Projects/Linked Data/api/b.md', '/Projects/Linked Data/api/final.md']
    assert fs.cat_file('/Projects/Linked Data/api/b.md') == b'10/2026-10 Linked Data/261018-api/b.md'


def test_a_folder_no_handler_says_is_partitioned_shows_what_it_holds(tmp_path):
    _made(tmp_path / 'Book', '10/chapter.md', '11/261105 notes.md')
    fs = DesktopFileSystem({'Book': GppuFileSystem(tmp_path / 'Book')})
    assert sorted(fs.ls('/Book', detail=False)) == ['/Book/10', '/Book/11']
    assert fs.ls('/Book/11', detail=False) == ['/Book/11/261105 notes.md']


def test_a_folder_stored_before_its_handler_existed_is_identified_again(tmp_path, monkeypatch):
    from gppu.fs import handlers
    _made(tmp_path, 'Work/10/21/task/a.md')
    probe = handlers.probe

    def before(path):   # as gppufs read Work before WorkFolderHandler existed
        record = probe(path)
        if record.type == handlers.WorkFolderHandler.type:
            record.type = handlers.FolderHandler.type
        return record
    monkeypatch.setattr(handlers, 'probe', before)
    fs = DesktopFileSystem({'D': GppuFileSystem(tmp_path)})
    assert fs.ls('/D/Work', detail=False) == ['/D/Work/10']
    monkeypatch.setattr(handlers, 'probe', probe)
    source = GppuFileSystem(tmp_path)
    source.ls_sync(None)   # listed live, as a FileIndexer run lists it
    assert DesktopFileSystem({'D': source}).ls('/D/Work', detail=False) == ['/D/Work/task']
