"""gppu.fs.catalog: /lake/catalog served from a catalog held in memory, browsed through CatalogFileSystem and the desktop."""
import json
import socket
from uuid import UUID

import pytest

pytest.importorskip('fastapi')
import fsspec
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from gppu.fs.catalog import Catalog, CatalogFileSystem, _text, api, label, paths, where
from gppu.fs.catalog import catalog as locations
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs.vfs import DesktopFileSystem

LIBRARY, ROOT, FOLDER, FILE = (UUID(f'00000000-0000-0000-0000-00000000000{n}') for n in range(1, 5))


class Held:
    """A catalog in memory with the answers Catalog gives: one library under a tenant, and two locations sharing a name."""

    def __init__(self):
        self.asked = []

    def locations(self):
        return [{'id': 'tenant', 'name': 'Karelin', 'canonical': 'm365://karelin', 'parent': None, 'indexed': False},
                {'id': 'library', 'name': 'Statements', 'canonical': 'm365://karelin/sharepoint/Statements', 'parent': 'tenant', 'indexed': True},
                {'id': 'one', 'name': 'github', 'canonical': None, 'parent': None, 'indexed': False},
                {'id': 'two', 'name': 'github', 'canonical': None, 'parent': None, 'indexed': True}]

    def columns(self):
        return ['ContentType', '_StartDate', 'TaxYear']

    def entries(self, location=None, parent=None, path=None):
        if path is not None:
            if path.startswith('Karelin/Statements/') and path not in FOLDERS:
                raise LookupError(f'{path}: its index holds nothing there')
            location, parent = (None, FOLDERS[path]) if path in FOLDERS else ({'Karelin/Statements': 'library'}.get(path), None)
        if location is not None and location not in ('library', 'two'):
            raise LookupError(f'location {location}: the catalog holds nothing there')
        self.asked.append(location or parent)
        rows = {'library': [{'id': ROOT, 'kind': 'folder', 'name': 'Statements', 'size': 300, 'files': 2, 'folders': 1,
                             'modified': '2026-05-30T00:00:00+00:00', 'created': None, 'content_type': None, 'columns': {}}],
                ROOT: [{'id': FILE, 'kind': 'file', 'name': '2019 Statements.pdf', 'size': 100, 'files': None, 'folders': None,
                        'modified': '2026-05-30T00:00:00+00:00', 'created': '2026-05-04T00:00:00Z', 'content_type': 'Statement',
                        'columns': {'ContentType': 'Statement', '_StartDate': '2019-01-01'}},
                       {'id': FOLDER, 'kind': 'folder', 'name': 'Tax Forms', 'size': 200, 'files': 1, 'folders': 0,
                        'modified': None, 'created': None, 'content_type': 'Folder', 'columns': {'ContentType': 'Folder'}}]}
        return iter(rows.get(location or parent, []))

    def at(self, location, path):
        found = {('library', 'Statements'): ROOT, ('library', 'Statements/Tax Forms'): FOLDER}.get((location, path))
        if found is None:
            raise LookupError(f'location {location}: the catalog holds nothing at {path}')
        return found

    def entry(self, uid):
        return {'id': uid, 'kind': 'folder', 'name': 'x', 'instances': []}


PDF = 'm365://karelin/sharepoint/Statements/Statements/2019 Statements.pdf'
FOLDERS = {'Karelin/Statements/Statements': ROOT, 'Karelin/Statements/Statements/Tax Forms': FOLDER}   # the folders of the library, by path


def served(held):
    """/lake/catalog, and the Lake at /lake giving the bytes of the one object it holds."""
    app = FastAPI()
    app.mount('/lake/catalog', api(held))

    @app.get('/lake/{uri:path}')
    def content(uri: str):
        if uri != PDF:
            return Response(status_code=404)
        return Response(b'%PDF statements')
    return TestClient(app)


def browsed(held):
    return CatalogFileSystem(client=served(held))


def test_locations_are_folders_and_a_shared_name_is_told_apart_by_id():
    fs = browsed(Held())
    assert sorted(fs.ls('', detail=False)) == ['Karelin', 'github (one)', 'github (two)']
    assert fs.ls('Karelin', detail=False) == ['Karelin/Statements']
    assert fs.info('Karelin')['type'] == 'directory'


def test_a_library_is_browsed_by_ids_with_its_sources_dates():
    fs = browsed(Held())
    assert fs.ls('Karelin/Statements', detail=False) == ['Karelin/Statements/Statements']
    rows = {row['name']: row for row in fs.ls('Karelin/Statements/Statements')}
    pdf = rows['Karelin/Statements/Statements/2019 Statements.pdf']
    assert (pdf['type'], pdf['size'], pdf['id'], pdf['content_type']) == ('file', 100, str(FILE), 'Statement')
    assert pdf['columns'] == {'ContentType': 'Statement', '_StartDate': '2019-01-01'}
    assert pdf['ctime'] < pdf['mtime'] and 'uid' not in pdf   # a FUSE bridge reads uid as the owner's
    assert rows['Karelin/Statements/Statements/Tax Forms']['type'] == 'directory'
    assert fs.info('Karelin/Statements/Statements/2019 Statements.pdf') == pdf


def test_a_folder_is_listed_by_its_path_without_its_folder_above_listed_first():
    held = Held()
    fs = browsed(held)
    assert fs.ls('Karelin/Statements/Statements/Tax Forms') == []
    assert held.asked == [FOLDER]
    with pytest.raises(FileNotFoundError):
        fs.ls('Karelin/Statements/Missing')
    with pytest.raises(FileNotFoundError):
        fs.ls('Nowhere')


def test_a_folder_the_desktop_shows_is_listed_by_its_path_with_each_entrys_columns():
    app = FastAPI()
    app.mount('/lake/catalog', api(Held()))
    client = TestClient(app)
    assert client.get('/lake/catalog/columns').json() == [{'name': 'ContentType', 'label': 'Content Type'},
                                                          {'name': '_StartDate', 'label': 'Start Date'},
                                                          {'name': 'TaxYear', 'label': 'Tax Year'}]
    rows = [json.loads(line) for line in client.get('/lake/catalog/entries', params={'path': 'Karelin/Statements/Statements'}).iter_lines()]
    assert [(row['name'], row['columns']) for row in rows] == [('2019 Statements.pdf', {'ContentType': 'Statement', '_StartDate': '2019-01-01'}),
                                                               ('Tax Forms', {'ContentType': 'Folder'})]


def test_a_columns_value_is_shown_as_text():
    assert _text('2019-12-31T19:52:07Z') == '2019-12-31'   # the local date it falls on, the same in every zone from UTC-12 to UTC+4
    assert (_text(2023.0), _text(2.5), _text(None), _text('SunTrust')) == ('2023', '2.5', '', 'SunTrust')
    assert _text({'Label': 'Statement', 'WssId': 7, 'TermGuid': 'e7db99d3'}) == 'Statement'
    assert _text({'Url': 'https://karelin.sharepoint.com/x', 'Description': 'A2UDFJZW7PK5-793683518-112'}) == 'A2UDFJZW7PK5-793683518-112'
    assert _text([{'Label': 'a'}, {'Label': 'b'}]) == 'a, b'
    assert (label('_dlc_DocIdUrl'), label('Due_x0020_Date')) == ('dlc Doc Id Url', 'Due Date')


def test_a_path_is_in_the_location_whose_path_it_starts_with_longest():
    tree = paths(Held().locations())
    assert sorted(tree) == ['Karelin', 'Karelin/Statements', 'github (one)', 'github (two)']
    assert where(tree, 'Karelin/Statements/Statements/Tax Forms') == (tree['Karelin/Statements'], 'Statements/Tax Forms')
    assert where(tree, 'Nowhere/x') == (None, 'Nowhere/x')


def test_an_entry_is_read_as_the_lake_gives_it_at_its_address():
    fs = browsed(Held())
    assert fs.cat_file('Karelin/Statements/Statements/2019 Statements.pdf') == b'%PDF statements'
    with pytest.raises(PermissionError):
        fs.open('Karelin/Statements/Statements/new.pdf', 'wb')


def test_an_address_is_read_as_its_locations_path():
    fs = browsed(Held())
    assert fs.ls('m365://karelin/sharepoint/Statements/Statements', detail=False) == fs.ls('Karelin/Statements/Statements', detail=False)
    assert fs.info(PDF)['name'] == 'Karelin/Statements/Statements/2019 Statements.pdf'
    assert fs.cat_file(PDF) == b'%PDF statements'
    with pytest.raises(FileNotFoundError):
        fs.ls('m365://tulaco/sharepoint/Other')


def with_catalog(held, tmp_path, monkeypatch):
    """The one gppufs, its catalog's address from fsspec's configuration, as FSSPEC_GPPU_CATALOG gives it."""
    monkeypatch.setitem(fsspec.config.conf, 'gppu', {'catalog': 'http://testserver'})
    fs = fsspec.filesystem('gppu')
    fs.catalog.client = served(held)
    return fs


def test_gppufs_lists_and_opens_through_the_catalog_what_it_holds_no_index_for(tmp_path, monkeypatch):
    fs = with_catalog(Held(), tmp_path, monkeypatch)
    assert fs is GppuFileSystem() and fs.catalog is not None
    names = fs.ls('catalog://Karelin/Statements/Statements', detail=False)
    assert names == ['catalog://Karelin/Statements/Statements/2019 Statements.pdf', 'catalog://Karelin/Statements/Statements/Tax Forms']
    assert fs.ls('m365://karelin/sharepoint/Statements/Statements', detail=False) == names
    assert fs.info(PDF)['name'] == names[0] and fs.cat_file(names[0]) == b'%PDF statements'
    with fs.open(PDF) as file:
        assert file.read() == b'%PDF statements'
    (tmp_path / 'note.md').write_text('# here')
    assert [row['name'] for row in fs.ls(tmp_path.as_posix())] == [(tmp_path / 'note.md').as_posix()]   # its own store is its own


def test_gppufs_has_no_catalog_unless_one_is_named_and_reaches_only_one(tmp_path, monkeypatch):
    assert GppuFileSystem().catalog is None
    GppuFileSystem.clear_instance_cache()
    fs = with_catalog(Held(), tmp_path, monkeypatch)
    assert GppuFileSystem(catalog='http://testserver') is fs
    with pytest.raises(ValueError):
        GppuFileSystem(catalog='https://elsewhere')


def test_the_desktop_shows_the_catalog_beside_its_other_sources():
    desktop = DesktopFileSystem({'Catalog': browsed(Held())})
    assert desktop.ls('/Catalog/Karelin', detail=False) == ['/Catalog/Karelin/Statements']
    row = desktop.info('/Catalog/Karelin/Statements/Statements/2019 Statements.pdf')
    assert (row['name'], row['type'], row['size']) == ('/Catalog/Karelin/Statements/Statements/2019 Statements.pdf', 'file', 100)
    names = desktop.ls('/Catalog/Karelin/Statements/Statements', detail=False)
    assert names == ['/Catalog/Karelin/Statements/Statements/2019 Statements.pdf', '/Catalog/Karelin/Statements/Statements/Tax Forms']


def test_a_location_on_this_host_by_its_handlers_access_is_read_in_its_folder(tmp_path):
    """A location whose uri names another host is read on this host in the folder its handler's access names here, and still named
    by its uri."""
    host = socket.gethostname().split('.')[0].casefold()
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'note.md').write_text('# note')
    records = [{'id': 'top', 'parent_id': None, 'status': 'active', 'flags': 0,
                'meta': {'display_name': 'Top', 'uri': 'file://elsewhere/srv/top', 'status': 'active'},
                'data': {'handler': {'access': {host: tmp_path.as_posix()}}}},
               {'id': 'inner', 'parent_id': 'top', 'status': 'active', 'flags': 0,
                'meta': {'display_name': 'Inner', 'uri': 'file://elsewhere/srv/top/sub', 'status': 'active'}, 'data': {}}]
    found = locations(records)
    assert str(found.location('top').uri_of('sub')) == 'file://elsewhere/srv/top/sub'
    assert found.location('top').container('sub').ls(detail=False) == ['note.md']
    assert found.location('inner').container().ls(detail=False) == ['note.md']   # below the folder of the location above it


def kept(indexes, uri, name, written='261031.120000.000'):
    """Where the Lake keeps an index as FileIndexer sends it: indexes/{host}/{folder without a drive's colon}/{when} {host} {name}."""
    host, _, folder = uri.partition('://')[2].partition('/')
    there = indexes / host / folder.replace(':', '')
    there.mkdir(parents=True, exist_ok=True)
    return there / f'{written} {host} {name}'


def test_the_catalog_lists_a_location_from_the_latest_index_the_lake_keeps_at_or_above_it(tmp_path):
    dev = tmp_path / 'Dev'
    (dev / 'sub').mkdir(parents=True)
    (dev / 'note.md').write_text('# note', encoding='utf-8')
    (dev / 'sub' / 'a.csv').write_text('a,b\n1,2\n', encoding='utf-8')
    fs = GppuFileSystem()
    with fs.run():
        fs.ls(dev, recurse=True, refresh=True)
    indexes = tmp_path / 'indexes'
    kept(indexes, 'file://alex-pc/D:/Dev', 'Dev.gppufs.sqlite').write_bytes((dev / '.Dev.gppufs.sqlite').read_bytes())
    kept(indexes, 'file://alex-pc/D:/Dev', 'Dev.gppufs.sqlite', '261030.120000.000').write_bytes(b'not read: an older index')
    records = [{'id': 'host', 'parent_id': None, 'meta': {'uri': 'file://alex-pc', 'display_name': 'Alex-PC'}, 'data': {}},
               {'id': 'data', 'parent_id': 'host', 'meta': {'uri': 'file://alex-pc/D:', 'display_name': 'data'}, 'data': {}},
               {'id': 'dev', 'parent_id': 'data', 'meta': {'uri': 'file://alex-pc/D:/Dev', 'display_name': 'Dev'}, 'data': {}},
               {'id': 'work', 'parent_id': 'data', 'meta': {'uri': 'file://alex-pc/D:/Work', 'display_name': 'Work'}, 'data': {}}]
    found = Catalog(lambda: records, indexes)
    assert sorted((row['id'], row['parent'], row['indexed']) for row in found.locations()) == [
        ('data', 'host', False), ('dev', 'data', True), ('host', None, False)]
    root = list(found.entries(location='dev'))
    assert [(row['name'], row['kind']) for row in root] == [('note.md', 'file'), ('sub', 'folder')]
    assert root[0]['size'] == 6 and root[0]['id'].startswith('1003') and root[0]['modified'] and root[0]['created']
    assert [row['name'] for row in found.entries(path='Alex-PC/data/Dev/sub')] == ['a.csv']   # held by the index above it
    sub = found.at('dev', 'sub')
    assert [row['name'] for row in found.entries(parent=sub)] == ['a.csv']
    assert (found.entry(sub)['path'], found.entry(sub)['kind']) == ('sub', 'folder')
    with pytest.raises(LookupError):
        list(found.entries(path='Alex-PC/data/Dev/missing'))
    with pytest.raises(LookupError):
        list(found.entries(location='work'))   # no index the Lake keeps holds it


def test_a_librarys_content_type_and_columns_come_from_its_index(tmp_path):
    """A SharePoint library's index holds each item as gppufs's m365 store lists it, its content type and columns with it."""
    import sqlite3
    from contextlib import closing
    index = kept(tmp_path / 'indexes', 'm365://karelin/sharepoint/Statements', 'Statements.gppufs.sqlite')

    def row(path, kind, columns=None, content_type=None):
        own = {'id': f'10030100-0000-0000-0000-00000000000{len(path)}', 'type': kind, 'size': 0 if kind == 'folder' else 100,
               'modified_at': '2026-05-30 00:00:00+00:00', 'files': None, 'folders': None}
        return path, json.dumps({'name': path, 'type': 'directory' if kind == 'folder' else 'file', 'created_at': '2026-05-04T00:00:00Z',
                                 'content_type': content_type, 'columns': columns or {}, 'gppu': own})
    with closing(sqlite3.connect(index)) as db:
        db.execute('CREATE TABLE gppufs_entries (path TEXT PRIMARY KEY, metadata TEXT NOT NULL, children TEXT)')
        db.executemany('INSERT INTO gppufs_entries (path, metadata) VALUES (?, ?)', [
            row('.', 'folder'),
            row('a.pdf', 'file', {'ContentType': 'Statement', '_StartDate': '2019-01-01T08:00:00Z', 'FileLeafRef': 'a.pdf'}, 'Statement'),
            row('b.pdf', 'file', {'ContentType': 'Tax Form', 'TaxYear': 2023.0, 'FileLeafRef': 'b.pdf'}, 'Tax Form')])
        db.commit()
    records = [{'id': 'tenant', 'parent_id': None, 'meta': {'uri': 'm365://karelin', 'display_name': 'Karelin'}, 'data': {}},
               {'id': 'library', 'parent_id': 'tenant', 'meta': {'uri': 'm365://karelin/sharepoint/Statements', 'display_name': 'Statements'}, 'data': {}}]
    found = Catalog(lambda: records, tmp_path / 'indexes')
    assert found.columns() == ['ContentType', 'TaxYear', '_StartDate']
    rows = {row['name']: row for row in found.entries(path='Karelin/Statements')}
    assert rows['a.pdf']['columns'] == {'ContentType': 'Statement', '_StartDate': '2019-01-01'}
    assert (rows['b.pdf']['content_type'], rows['b.pdf']['columns'], rows['b.pdf']['created']) == (
        'Tax Form', {'ContentType': 'Tax Form', 'TaxYear': '2023'}, '2026-05-04T00:00:00Z')
