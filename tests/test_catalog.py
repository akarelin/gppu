"""gppu.catalog: /catalog served from a catalog held in memory, browsed through CatalogFileSystem and the desktop."""
from uuid import UUID

import pytest

pytest.importorskip('fastapi')
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gppu.catalog import CatalogFileSystem, api
from gppu.desktop import DesktopFileSystem

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

    def entries(self, location=None, parent=None):
        if location is not None and location not in ('library', 'two'):
            raise LookupError(f'location {location}: the catalog holds nothing there')
        self.asked.append(location or parent)
        rows = {'library': [{'id': ROOT, 'kind': 'folder', 'name': 'Statements', 'size': 300, 'files': 2, 'folders': 1,
                             'modified': '2026-05-30T00:00:00+00:00', 'created': None, 'content_type': None}],
                ROOT: [{'id': FILE, 'kind': 'file', 'name': '2019 Statements.pdf', 'size': 100, 'files': None, 'folders': None,
                        'modified': '2026-05-30T00:00:00+00:00', 'created': '2026-05-04T00:00:00Z', 'content_type': 'Document'},
                       {'id': FOLDER, 'kind': 'folder', 'name': 'Tax Forms', 'size': 200, 'files': 1, 'folders': 0,
                        'modified': None, 'created': None, 'content_type': 'Folder'}]}
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
    app.mount('/catalog', api(held))
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
    assert (pdf['type'], pdf['size'], pdf['id'], pdf['content_type']) == ('file', 100, str(FILE), 'Document')
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
