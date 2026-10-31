"""gppu.fs.catalog's Catalog on its database, Linked Data's fs.instances: an index loaded as its folder's latest copy, a file the
Lake saves recorded, and what is in the locations read back, every call through the fs API to Postgres and back (conftest's ld,
on the Postgres server LD_TEST_DSN names)."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

pytest.importorskip('fastapi')   # gppu's ld extra; the build's tests install gppu without it

from gppu.fs.catalog import Catalog
from gppu.fs.gppufs import GppuFileSystem


@pytest.fixture(scope='module')
def ld(ld):
    """The fs API (conftest's ld) with a host, its drive, two folders on it and a tenant's library as locations."""
    made = {}
    for key, parent, type, uri, name in (('host', None, 'host', 'file://alex-pc', 'Alex-PC'),
                                          ('data', 'host', 'location', 'file://alex-pc/D:', 'data'),
                                          ('dev', 'data', 'location', 'file://alex-pc/D:/Dev', 'Dev'),
                                          ('work', 'data', 'location', 'file://alex-pc/D:/Work', 'Work'),
                                          ('tenant', None, 'location', 'm365://karelin', 'Karelin'),
                                          ('library', 'tenant', 'location', 'm365://karelin/sharepoint/Statements', 'Statements')):
        r = ld.post('/fs/locations', json={'type': type, 'parent_id': made.get(parent), 'data': {},
                                           'meta': {'uri': uri, 'display_name': name, 'status': 'active'}})
        assert r.status_code == 200, r.text
        made[key] = r.json()['id']
    ld.made = made
    return ld


def catalog_of(ld):
    return Catalog(lambda: ld.get('/fs/locations', params={'limit': 1000}).json()['items'], ld)


def indexed(folder: Path) -> Path:
    """The index gppufs writes in folder, read and written in one run."""
    fs = GppuFileSystem()
    with fs.run():
        fs.ls(folder, recurse=True, refresh=True)
    return folder / f'.{folder.name}.gppufs.sqlite'


def test_an_index_is_loaded_as_its_folders_latest_copy_and_read_back(ld, tmp_path):
    dev = tmp_path / 'Dev'
    (dev / 'sub').mkdir(parents=True)
    (dev / 'note.md').write_text('# note', encoding='utf-8')
    (dev / 'old.md').write_text('# old', encoding='utf-8')
    (dev / 'sub' / 'a.csv').write_text('a,b\n1,2\n', encoding='utf-8')
    found = catalog_of(ld)
    found.load('file://alex-pc/D:/Dev/.Dev.gppufs.sqlite', indexed(dev))
    tree = {row['id']: row for row in found.locations()}
    assert {(row['name'], row['indexed']) for row in tree.values()} == {('Alex-PC', False), ('data', False), ('Dev', True)}
    root = list(found.entries(location=ld.made['dev']))
    assert [(row['name'], row['kind']) for row in root] == [('note.md', 'file'), ('old.md', 'file'), ('sub', 'folder')]
    assert root[0]['size'] == 6 and root[0]['id'].startswith('1003') and root[0]['modified'] and root[0]['created']
    assert [row['name'] for row in found.entries(path='Alex-PC/data/Dev/sub')] == ['a.csv']
    sub = found.at(ld.made['dev'], 'sub')
    assert [row['name'] for row in found.entries(parent=sub)] == ['a.csv']
    assert (found.entry(sub)['uri'], found.entry(sub)['index']) == ('file://alex-pc/D:/Dev/sub', 'file://alex-pc/D:/Dev')
    assert found.info('file://alex-pc/D:/Dev')['parent'] == ld.made['dev']   # a location's folder is inside the location
    first = found.loaded('file://alex-pc/D:/Dev')['loaded']
    with pytest.raises(LookupError):
        found.loaded('file://alex-pc/D:/Dev/sub')   # held inside Dev's index, no index of its own

    (dev / 'old.md').unlink()
    found.load('file://alex-pc/D:/Dev/.Dev.gppufs.sqlite', indexed(dev))
    assert [row['name'] for row in found.entries(location=ld.made['dev'])] == ['note.md', 'sub']   # gone from the latest copy
    assert found.loaded('file://alex-pc/D:/Dev')['loaded'] > first
    with pytest.raises(LookupError):
        found.info('file://alex-pc/D:/Dev/old.md')
    with pytest.raises(LookupError):
        list(found.entries(location=ld.made['work']))   # the catalog holds nothing there


def test_a_file_the_lake_saves_is_recorded_inside_the_folders_above_it(ld):
    found = catalog_of(ld)
    row = found.record('file://five/mnt/S1/Lake/timeseries/2026/Screenshots/10/Screenshot 1.png', 'file',
                       {'kind': 'file', 'size': 3, 'modified': '2026-10-31 10:00:00-07:00'})
    assert (row['name'], row['size'], row['kind']) == ('Screenshot 1.png', 3, 'file')
    assert [entry['name'] for entry in found.entries(uri='file://five/mnt/S1/Lake/timeseries/2026/Screenshots/10')] == ['Screenshot 1.png']
    assert [entry['name'] for entry in found.entries(uri='file://five/mnt/S1/Lake')] == ['timeseries']
    assert found.info('file://five/mnt')['parent'] is None   # the top of a host no location holds
    again = found.record('file://five/mnt/S1/Lake/timeseries/2026/Screenshots/10/Screenshot 1.png', 'file', {'kind': 'file', 'size': 5})
    assert (again['id'], again['size']) == (row['id'], 5)   # saved again, the same instance


def test_a_librarys_content_type_and_columns_come_from_its_index(ld, tmp_path):
    """A SharePoint library's index holds each item as gppufs's m365 store lists it, its content type and columns with it."""
    index = tmp_path / '.Statements.gppufs.sqlite'

    def row(path, kind, columns=None, content_type=None):
        own = {'id': str(__import__('gppu').uuid_create(0x1003)), 'type': kind, 'size': 0 if kind == 'folder' else 100,
               'modified_at': '2026-05-30 00:00:00+00:00', 'files': None, 'folders': None, 'handlers': [kind]}
        return path, json.dumps({'name': path, 'created_at': '2026-05-04T00:00:00Z', 'content_type': content_type,
                                 'columns': columns or {}, 'gppu': own})
    with closing(sqlite3.connect(index)) as db:
        db.execute('CREATE TABLE gppufs_entries (path TEXT PRIMARY KEY, metadata TEXT NOT NULL, children TEXT)')
        db.executemany('INSERT INTO gppufs_entries (path, metadata) VALUES (?, ?)', [
            row('.', 'folder'),
            row('a.pdf', 'file', {'ContentType': 'Statement', '_StartDate': '2019-01-01T08:00:00Z', 'FileLeafRef': 'a.pdf'}, 'Statement'),
            row('b.pdf', 'file', {'ContentType': 'Tax Form', 'TaxYear': 2023.0, 'FileLeafRef': 'b.pdf'}, 'Tax Form')])
        db.commit()
    found = catalog_of(ld)
    found.load('m365://karelin/sharepoint/Statements/.Statements.gppufs.sqlite', index)
    assert found.columns() == ['ContentType', 'TaxYear', '_StartDate']
    rows = {row['name']: row for row in found.entries(path='Karelin/Statements')}
    assert rows['a.pdf']['columns'] == {'ContentType': 'Statement', '_StartDate': '2019-01-01'}
    assert (rows['b.pdf']['content_type'], rows['b.pdf']['columns'], rows['b.pdf']['created']) == (
        'Tax Form', {'ContentType': 'Tax Form', 'TaxYear': '2023'}, '2026-05-04T00:00:00Z')


def test_an_index_whose_rows_have_no_ids_is_refused(ld, tmp_path):
    index = tmp_path / '.Old.gppufs.sqlite'
    with closing(sqlite3.connect(index)) as db:
        db.execute('CREATE TABLE gppufs_entries (path TEXT PRIMARY KEY, metadata TEXT NOT NULL, children TEXT)')
        db.execute('INSERT INTO gppufs_entries (path, metadata) VALUES (?, ?)', ('.', json.dumps({'gppu': {'type': 'folder', 'handlers': ['folder']}})))
        db.commit()
    with pytest.raises(ValueError):
        catalog_of(ld).load('file://alex-pc/D:/Work/.Old.gppufs.sqlite', index)


def test_a_folder_no_longer_indexed_is_unloaded_with_what_its_index_put_there(ld, tmp_path):
    work = tmp_path / 'Work'
    (work / 'notes').mkdir(parents=True)
    (work / 'notes' / 'n.md').write_text('# n', encoding='utf-8')
    found = catalog_of(ld)
    found.load('file://alex-pc/D:/Work/.Work.gppufs.sqlite', indexed(work))
    assert [row['name'] for row in found.entries(location=ld.made['work'])] == ['notes']
    found.unload('file://alex-pc/D:/Work')
    for uri in ('file://alex-pc/D:/Work', 'file://alex-pc/D:/Work/notes', 'file://alex-pc/D:/Work/notes/n.md'):
        with pytest.raises(LookupError):
            found.info(uri)
