"""gppu.fs.catalog: /lake/catalog served from a catalog held in memory, browsed through CatalogFileSystem and the desktop."""
import json
import socket
from uuid import UUID

import pytest

pytest.importorskip('fastapi')
import fsspec
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from gppu.fs.catalog import CatalogFileSystem, _text, api, label, paths, where
from gppu.fs.catalog import catalog as locations
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs.vfs import DesktopFileSystem

LIBRARY, ROOT, FOLDER, FILE = (UUID(f'00000000-0000-0000-0000-00000000000{n}') for n in range(1, 5))


class Held:
    """A catalog in memory with the answers Catalog gives: one library under a tenant, and two locations sharing a name."""

    def __init__(self):
        self.asked = []

    def locations(self):
        return [{'id': 'tenant', 'name': 'Karelin', 'uid': 'box-karelin', 'canonical': 'm365://karelin', 'parent': None, 'lake_id': None},
                {'id': 'library', 'name': 'Statements', 'uid': None, 'canonical': 'm365://karelin/sharepoint/Statements',
                 'parent': 'tenant', 'lake_id': 142},
                {'id': 'one', 'name': 'github', 'uid': 'github', 'canonical': None, 'parent': None, 'lake_id': None},
                {'id': 'two', 'name': 'github', 'uid': 'system-github', 'canonical': None, 'parent': None, 'lake_id': 226}]

    def columns(self):
        return ['ContentType', '_StartDate', 'TaxYear']

    def entries(self, location=None, parent=None, path=None):
        if path is not None:
            parent = {'Karelin/Statements/Statements': ROOT}.get(path)
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


def test_locations_are_folders_and_a_shared_name_is_told_apart_by_uid():
    fs = browsed(Held())
    assert sorted(fs.ls('', detail=False)) == ['Karelin', 'github (github)', 'github (system-github)']
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


def test_a_path_not_listed_yet_is_resolved_into_its_id_by_the_catalog():
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
    assert sorted(tree) == ['Karelin', 'Karelin/Statements', 'github (github)', 'github (system-github)']
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
    """A location whose canonical address names another host is read on this host in the folder its handler's access names here,
    and still named by its canonical address."""
    host = socket.gethostname().split('.')[0].casefold()
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'note.md').write_text('# note')
    records = [{'id': 'top', 'name': 'Top', 'parent_id': None, 'status': 'active', 'flags': 0, 'meta': {},
                'data': {'uid': 'top', 'canonical': 'file://elsewhere/srv/top',
                         'handler': {'kind': 'fileSystem', 'access': {host: tmp_path.as_posix()}}}},
               {'id': 'inner', 'name': 'Inner', 'parent_id': 'top', 'status': 'active', 'flags': 0, 'meta': {},
                'data': {'uid': 'inner', 'canonical': 'file://elsewhere/srv/top/sub'}}]
    found = locations(records)
    assert str(found.location('top').uri_of('sub')) == 'file://elsewhere/srv/top/sub'
    assert found.location('top').container('sub').ls(detail=False) == ['note.md']
    assert found.location('inner').container().ls(detail=False) == ['note.md']   # below the folder of the location above it
