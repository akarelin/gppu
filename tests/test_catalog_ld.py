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
    assert root[0]['size'] == 6 and root[0]['id'].startswith('1002') and root[0]['modified'] and root[0]['created']   # a file
    assert [row['name'] for row in found.entries(path='Alex-PC/data/Dev/sub')] == ['a.csv']
    sub = found.at(ld.made['dev'], 'sub')
    assert [row['name'] for row in found.entries(parent=sub)] == ['a.csv']
    assert (found.entry(sub)['uri'], found.entry(sub)['type']) == ('file://alex-pc/D:/Dev/sub', 'folder')   # a folder is a file
    assert found.info('file://alex-pc/D:/Dev')['parent'] == ld.made['dev']   # a location's folder is inside the location
    note = found.instances('file://alex-pc/D:/Dev/note.md')   # its one copy, inside its file, by its gppufs id
    assert [(row['uri'], row['index'], row['id'][:4]) for row in note] == [('file://alex-pc/D:/Dev/note.md', 'file://alex-pc/D:/Dev', '1003')]
    copy = ld.get(f"/fs/instances/{note[0]['id']}").json()
    assert (copy['type'], copy['parent_id']) == ('instance', root[0]['id'])
    assert found.entry(root[0]['id'])['span']['start']   # the file's span starts when its source says it was created
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


def test_every_hosts_synced_copy_is_an_instance_of_the_cloud_folders_file(ld, tmp_path):
    """A local folder a link links to its cloud folder: each host's copy of a file there is an instance of the one file at the cloud
    folder's uri and the same path, and the local location lists the cloud folder's files."""
    made = {}
    for key, parent, type, uri, name in (('laptop', None, 'host', 'file://alex-laptop', 'Alex-Laptop'),
                                          ('s1', None, 'location', 'smb://s1.karel.in', 's1'),
                                          ('cloud', 's1', 'location', 'smb://s1.karel.in/SD/2026.work', 'Work'),
                                          ('here', 'data', 'location', 'file://alex-pc/D:/Synced', 'Synced'),
                                          ('there', 'laptop', 'location', 'file://alex-laptop/C:/Synced', 'Synced')):
        r = ld.post('/fs/locations', json={'type': type, 'parent_id': made.get(parent, ld.made.get(parent)), 'data': {},
                                           'meta': {'uri': uri, 'display_name': name, 'status': 'active'}})
        made[key] = r.json()['id']
    for local in ('here', 'there'):
        assert ld.post('/fs/links', json={'type': 'link', 'from_id': made[local], 'to_id': made['cloud']}).status_code == 200
    copies = {}
    for host, root in (('alex-pc', 'D:'), ('alex-laptop', 'C:')):
        folder = tmp_path / host / 'Synced'
        (folder / '10').mkdir(parents=True)
        (folder / '10' / 'plan.md').write_text(f'# plan on {host}', encoding='utf-8')
        copies[host] = indexed(folder)
    found = catalog_of(ld)
    found.load('file://alex-pc/D:/Synced/.Synced.gppufs.sqlite', copies['alex-pc'])
    found.load('file://alex-laptop/C:/Synced/.Synced.gppufs.sqlite', copies['alex-laptop'])
    plan = found.info('file://alex-pc/D:/Synced/10/plan.md')
    assert plan['uri'] == 'smb://s1.karel.in/SD/2026.work/10/plan.md' == found.info('file://alex-laptop/C:/Synced/10/plan.md')['uri']
    assert sorted(row['uri'] for row in found.instances('smb://s1.karel.in/SD/2026.work/10/plan.md')) == [
        'file://alex-laptop/C:/Synced/10/plan.md', 'file://alex-pc/D:/Synced/10/plan.md']
    assert found.info('smb://s1.karel.in/SD/2026.work')['parent'] == made['cloud']   # the cloud folder's file, inside its location
    assert [row['name'] for row in found.entries(location=made['here'])] == ['10'] == [row['name'] for row in found.entries(location=made['cloud'])]
    found.unload('file://alex-laptop/C:/Synced')   # one host's copy gone: the file stays, an instance of the other
    assert [row['uri'] for row in found.instances('smb://s1.karel.in/SD/2026.work/10/plan.md')] == ['file://alex-pc/D:/Synced/10/plan.md']
    found.unload('file://alex-pc/D:/Synced')   # the last copy gone: the file goes with it
    with pytest.raises(LookupError):
        found.info('smb://s1.karel.in/SD/2026.work/10/plan.md')
