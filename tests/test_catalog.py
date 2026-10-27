"""gppu.fs.catalog: /lake/catalog served from a catalog held in memory, browsed through CatalogFileSystem and the desktop."""
import json
from uuid import UUID

import pytest

pytest.importorskip('fastapi')
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gppu.fs.catalog import CatalogFileSystem, _text, api, label, paths, where
from gppu.fs.vfs import DesktopFileSystem

LIBRARY, ROOT, FOLDER, FILE = (UUID(f'00000000-0000-0000-0000-00000000000{n}') for n in range(1, 5))


class Held:
    """A catalog in memory with the answers Catalog gives: one library under a tenant, and two locations sharing a name."""

    def __init__(self):
        self.asked = []

    def locations(self):
        return [{'id': 'tenant', 'name': 'Karelin', 'uid': 'box-karelin', 'parent': None, 'lake_id': None},
                {'id': 'library', 'name': 'Statements', 'uid': None, 'parent': 'tenant', 'lake_id': 142},
                {'id': 'one', 'name': 'github', 'uid': 'github', 'parent': None, 'lake_id': None},
                {'id': 'two', 'name': 'github', 'uid': 'system-github', 'parent': None, 'lake_id': 226}]

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


def browsed(held):
    app = FastAPI()
    app.mount('/lake/catalog', api(held))
    return CatalogFileSystem(client=TestClient(app))


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


def test_the_catalog_holds_no_content():
    fs = browsed(Held())
    with pytest.raises(PermissionError):
        fs.open('Karelin/Statements/Statements/2019 Statements.pdf').read()


def test_the_desktop_shows_the_catalog_beside_its_other_sources():
    desktop = DesktopFileSystem({'Catalog': browsed(Held())})
    assert desktop.ls('/Catalog/Karelin', detail=False) == ['/Catalog/Karelin/Statements']
    row = desktop.info('/Catalog/Karelin/Statements/Statements/2019 Statements.pdf')
    assert (row['name'], row['type'], row['size']) == ('/Catalog/Karelin/Statements/Statements/2019 Statements.pdf', 'file', 100)
    names = desktop.ls('/Catalog/Karelin/Statements/Statements', detail=False)
    assert names == ['/Catalog/Karelin/Statements/Statements/2019 Statements.pdf', '/Catalog/Karelin/Statements/Statements/Tax Forms']
