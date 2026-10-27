"""gppu.ld and gppu.ld.fs on Postgres: the standard's schemas ld and fs (tests/ld.sql) in a database of their own, made for
these tests and dropped after them; every call goes through the API to Postgres and back. LD_TEST_DSN is the Postgres server
to make it on."""
import os
from uuid import UUID, uuid4

import pytest

pytest.importorskip('fastapi')   # gppu's ld extra; the build's tests install gppu without it
if not os.environ.get('LD_TEST_DSN'):
    pytest.skip('LD_TEST_DSN, the Postgres these tests make their database on, is not set', allow_module_level=True)

import psycopg
from pathlib import Path
from fastapi.testclient import TestClient

from gppu import Env
from gppu.data import _SQABase
from gppu.fs import catalog as locations
from gppu.ld import fs as files
from gppu.ld import serve

DSN = os.environ['LD_TEST_DSN']
DB = 'ld_test'


@pytest.fixture(scope='module')
def api():
    """The core and the fs API on a database made from the standard's SQL."""
    with psycopg.connect(DSN, autocommit=True) as server:
        server.execute(f'DROP DATABASE IF EXISTS {DB}')
        server.execute(f'CREATE DATABASE {DB}')
    dsn = DSN.rsplit('/', 1)[0] + '/' + DB
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute((Path(__file__).parent / 'ld.sql').read_text(encoding='utf-8'))
    previous, initialized = Env.data, Env.initialized
    Env._load_dict({'db': dsn})   # the store's `db`, as an app's configuration gives it
    try:
        with TestClient(serve({'/fs': files.app}, _SQABase())) as client:
            yield client
    finally:
        Env.reset()
        Env.data, Env.initialized = previous, initialized
        with psycopg.connect(DSN, autocommit=True) as server:
            server.execute(f'DROP DATABASE {DB} WITH (FORCE)')


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def test_a_record_goes_to_the_table_its_type_is_in(api):
    node = ok(api.post('/records', json={'type': 'node', 'data': {'x': 1}}))
    activity = ok(api.post('/records', json={'type': 'activity', 'span': {'start': '2026-10-27T10:00:00Z', 'end': '2026-10-27T11:00:00Z'}}))
    assert UUID(node['id']).bytes[:8] == bytes([0x01]) + bytes(7)
    assert UUID(activity['id']).bytes[0] == 0x03
    assert node['flags'] == 0 and node['name'] == f"node-{node['id']}"
    assert activity['ts'].startswith('2026-10-27T10:00:00')


def test_a_type_no_table_of_the_path_has_is_refused(api):
    assert 'no table' in ok(api.post('/records', json={'type': 'markdown'}), 422)['detail']
    assert 'no table' in ok(api.post('/records', json={'type': 'nothing'}), 422)['detail']


def test_the_store_fills_its_own_columns(api):
    assert 'the store fills them' in ok(api.post('/records', json={'type': 'node', 'ts': '2026-10-27T10:00:00Z'}), 422)['detail']


def test_a_name_is_data_name_unless_one_is_sent(api):
    assert ok(api.post('/records', json={'type': 'node', 'data': {'name': 'From data'}}))['name'] == 'From data'
    assert ok(api.post('/records', json={'type': 'node', 'name': 'Sent', 'data': {'name': 'From data'}}))['name'] == 'Sent'


def test_an_update_merges_data_and_a_null_removes_a_key(api):
    node = ok(api.post('/records', json={'type': 'node', 'data': {'a': 1, 'b': 2}}))
    updated = ok(api.put(f"/records/{node['id']}", json={'data': {'b': None, 'c': 3}}))
    assert updated['data'] == {'a': 1, 'c': 3} and updated['updated']


def test_a_put_of_an_id_not_there_creates_it(api):
    id = UUID(bytes=bytes([0x01]) + uuid4().bytes[1:])
    assert ok(api.put(f'/records/{id}', json={'type': 'node'}))['id'] == str(id)
    assert ok(api.get(f'/records/{id}'))['type'] == 'node'


def test_a_link_joins_two_records(api):
    a, b = (ok(api.post('/records', json={'type': 'node'})) for _ in range(2))
    link = ok(api.post('/links', json={'type': 'link', 'from_id': a['id'], 'to_id': b['id']}))
    assert UUID(link['id']).bytes[0] == 0x02
    assert [l['id'] for l in ok(api.get(f"/records/{a['id']}/links"))['items']] == [link['id']]
    assert 'is not a record' in ok(api.post('/links', json={'type': 'link', 'from_id': a['id'], 'to_id': str(uuid4())}), 422)['detail']


def test_a_read_only_record_changes_only_its_flags(api):
    node = ok(api.post('/records', json={'type': 'node', 'flags': 1}))
    assert 'read only' in ok(api.put(f"/records/{node['id']}", json={'data': {'a': 1}}), 422)['detail']
    assert ok(api.put(f"/records/{node['id']}", json={'flags': 0}))['flags'] == 0
    assert ok(api.put(f"/records/{node['id']}", json={'data': {'a': 1}}))['data'] == {'a': 1}


def test_a_deleted_record_is_out_of_sight_and_read_by_its_id(api):
    parent = ok(api.post('/records', json={'type': 'node'}))
    child = ok(api.post('/records', json={'type': 'node', 'parent_id': parent['id']}))
    hidden = ok(api.post('/records', json={'type': 'node', 'parent_id': parent['id'], 'flags': 8}))
    ok(api.delete(f"/records/{child['id']}"), 204)
    assert ok(api.get(f"/records/{child['id']}"))['flags'] == 4
    assert ok(api.get(f"/records/{parent['id']}/records")) == []
    assert ok(api.get('/records', params={'filters': f'{{"parent_id": {{"$eq": "{parent["id"]}"}}}}'}))['total'] == 0
    assert ok(api.get(f"/records/{hidden['id']}"))['flags'] == 8
    assert 'read only' in ok(api.put(f"/records/{child['id']}", json={'data': {'a': 1}}), 422)['detail']


def test_types_are_searched_by_slug(api):
    found = ok(api.get('/types', params={'filters': '{"slug": {"$eq": "node"}}'}))['items']
    assert [(t['slug'], t['shard']) for t in found] == [('node', 0x01)]


def test_the_file_system_is_in_its_own_schema(api):
    root = ok(api.post('/fs/locations', json={'type': 'file_system', 'provider': 'file_system', 'service': 'smb',
                                              'data': {'uid': 'root', 'canonical': 'file:///root', 'handler': {'provider': 'file'}}}))
    file = ok(api.post('/fs/files', json={'type': 'markdown', 'parent_id': root['id'], 'name': 'a.md', 'data': {'extension': 'md'}}))
    instance = ok(api.post('/fs/instances', json={'type': 'instance', 'parent_id': file['id'], 'data': {'source': 'test', 'size': 3}}))
    assert [UUID(r['id']).bytes[0] for r in (root, file, instance)] == [0x11, 0x13, 0x14]
    assert root['provider'] == 'file_system' and root['service'] == 'smb'
    assert ok(api.get(f"/records/{file['id']}"))['type'] == 'markdown'   # every table inherits ld.records
    assert [t['slug'] for t in ok(api.get('/fs/types', params={'filters': '{"slug": {"$eq": "markdown"}}'}))['items']] == ['markdown']


def test_gppufs_makes_its_catalog_from_the_locations(api):
    root = ok(api.post('/fs/locations', json={'type': 'file_system', 'provider': 'file_system', 'name': 'Root',
                                              'data': {'uid': 'cat-root', 'canonical': 'file:///cat-root', 'handler': {'provider': 'file'}}}))
    ok(api.post('/fs/locations', json={'type': 'location', 'parent_id': root['id'], 'name': 'Inner',
                                       'data': {'uid': 'cat-inner', 'canonical': 'file:///cat-root/inner'}}))
    ok(api.post('/fs/locations', json={'type': 'location', 'parent_id': root['id'], 'flags': 16,
                                       'data': {'uid': 'cat-archived', 'canonical': 'file:///cat-root/archived'}}))
    locations.client = api
    catalog = locations.catalog()
    assert {'cat-root', 'cat-inner'} <= catalog.locations.keys() and 'cat-archived' not in catalog.locations
    assert catalog.locations['cat-inner']['parent'] == 'cat-root'
