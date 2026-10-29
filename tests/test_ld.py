"""gppu.ld, gppu.ld.fs and gppu.ld.sessions on Postgres: the standard's schemas ld, fs and sessions (tests/ld.sql) in a database
of their own, made for these tests and dropped after them; every call goes through the API to Postgres and back. LD_TEST_DSN is the
Postgres server to make it on."""
import asyncio
import os
from uuid import UUID, uuid4

import pytest

pytest.importorskip('fastapi')   # gppu's ld extra; the build's tests install gppu without it
if not os.environ.get('LD_TEST_DSN'):
    pytest.skip('LD_TEST_DSN, the Postgres these tests make their database on, is not set', allow_module_level=True)

import psycopg
from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from gppu import Env, uuid_create
from gppu.data import _SQABase
from gppu.fs import catalog as locations
from gppu.ld import fs as files
from gppu.ld import Page, Params, api_at, serve, sessions

DSN = os.environ['LD_TEST_DSN']
DB = f'gppu_ld_test_{uuid4().hex[:12]}'   # its own, so no other database on the server is touched
ordered = APIRouter()


@ordered.get('/ordered/{id}/messages', response_model=Page[sessions.Message])
async def messages(id: UUID, params: Params = Depends()):
    """A session's messages in the order of their lines in its file, then of their ids, a page at a time, as Linked Data's
    service reads them."""
    return await sessions.Message.search(params, sessions.Message.parent_id == id, order=(sessions.Message.meta['line'].as_integer(),))


@pytest.fixture(scope='module')
def api():
    """The core, the fs API and the sessions API, and a session's messages in order, on a database made from gppu.ld's SQL (ld.sql)."""
    with psycopg.connect(DSN, autocommit=True) as server:
        server.execute(f'CREATE DATABASE {DB}')
    dsn = DSN.rsplit('/', 1)[0] + '/' + DB
    previous, initialized = Env.data, Env.initialized
    try:
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute((Path(__file__).parent / 'ld.sql').read_text(encoding='utf-8'))
        Env._load_dict({'db': dsn})   # the store's `db`, as an app's configuration gives it
        apis = {'/fs': files.app, '/sessions': sessions.app, '/ordered': api_at('/ordered', 'ordered', "A session's messages in order.", ordered)}
        with TestClient(serve(apis, _SQABase()), backend_options={'loop_factory': asyncio.SelectorEventLoop}) as client:   # psycopg's async connections need the selector loop on Windows, as RAN's api.py runs it
            yield client
    finally:
        Env.reset()
        Env.data, Env.initialized = previous, initialized
        with psycopg.connect(DSN, autocommit=True) as server:
            server.execute(f'DROP DATABASE {DB} WITH (FORCE)')


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def header(record) -> bytes:
    """An id's first eight bytes: shard1, shard2, version 1 and five reserved bytes of 0."""
    return UUID(record['id']).bytes[:8]


def test_a_record_goes_to_the_table_its_type_is_in(api):
    node = ok(api.post('/records', json={'type': 'node', 'data': {'x': 1}}))
    entity = ok(api.post('/records', json={'type': 'entity'}))
    activity = ok(api.post('/records', json={'type': 'activity', 'span': {'start': '2026-10-27T10:00:00Z', 'end': '2026-10-27T11:00:00Z'}}))
    message = ok(api.post('/records', json={'type': 'message'}))
    assert header(node) == header(entity) == bytes([0x00, 0x01, 1]) + bytes(5)
    assert header(activity) == header(message) == bytes([0x00, 0x20, 1]) + bytes(5)
    assert node['flags'] == 0 and node['name'] == f"node-{node['id']}"
    assert activity['ts'].startswith('2026-10-27T10:00:00')


def test_a_type_no_table_of_the_path_has_is_refused(api):
    for type in ('markdown', 'host', 'cc', 'nothing'):   # fs's, fs's, fs's and sessions', none
        assert 'no table' in ok(api.post('/records', json={'type': type}), 422)['detail']


def test_the_store_fills_its_own_columns(api):
    assert 'the store fills them' in ok(api.post('/records', json={'type': 'node', 'ts': '2026-10-27T10:00:00Z'}), 422)['detail']


def test_a_name_is_data_name_unless_one_is_sent(api):
    assert ok(api.post('/records', json={'type': 'node', 'data': {'name': 'From data'}}))['name'] == 'From data'
    assert ok(api.post('/records', json={'type': 'node', 'name': 'Sent', 'data': {'name': 'From data'}}))['name'] == 'Sent'


def test_a_name_from_data_follows_it(api):
    node = ok(api.post('/records', json={'type': 'node', 'data': {'name': 'Before'}}))
    assert ok(api.put(f"/records/{node['id']}", json={'data': {'name': 'After'}}))['name'] == 'After'


def test_an_update_merges_data_and_a_null_removes_a_key(api):
    node = ok(api.post('/records', json={'type': 'node', 'data': {'a': 1, 'b': 2}}))
    updated = ok(api.put(f"/records/{node['id']}", json={'data': {'b': None, 'c': 3}}))
    assert updated['data'] == {'a': 1, 'c': 3} and updated['updated']


def test_a_put_of_an_id_not_there_creates_it(api):
    id = uuid_create(0x00, 0x01)   # made offline as the store makes them
    assert ok(api.put(f'/records/{id}', json={'type': 'node'}))['id'] == str(id)
    assert ok(api.get(f'/records/{id}'))['type'] == 'node'


def test_a_link_joins_two_records(api):
    a, b = (ok(api.post('/records', json={'type': 'node'})) for _ in range(2))
    link = ok(api.post('/links', json={'type': 'link', 'from_id': a['id'], 'to_id': b['id']}))
    assert header(link)[:2] == bytes([0x00, 0x10])
    assert [l['id'] for l in ok(api.get(f"/records/{a['id']}/links"))['items']] == [link['id']]


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


def test_flags_change_only_by_their_transitions(api):
    node = ok(api.post('/records', json={'type': 'node'}))
    assert 'change only by delete, archive, toggle hidden, toggle ro' in ok(api.put(f"/records/{node['id']}", json={'flags': 3}), 422)['detail']
    assert ok(api.put(f"/records/{node['id']}", json={'flags': 16}))['flags'] == 16   # archive
    assert 'change only by un-archive' in ok(api.put(f"/records/{node['id']}", json={'flags': 20}), 422)['detail']
    assert 'change only by un-archive' in ok(api.delete(f"/records/{node['id']}"), 422)['detail']
    assert ok(api.put(f"/records/{node['id']}", json={'flags': 0}))['flags'] == 0   # un-archive
    hidden = ok(api.post('/records', json={'type': 'node', 'flags': 8}))
    assert 'change only by toggle hidden' in ok(api.delete(f"/records/{hidden['id']}"), 422)['detail']
    system = ok(api.post('/records', json={'type': 'node', 'flags': 2}))
    assert 'no transition' in ok(api.put(f"/records/{system['id']}", json={'flags': 0}), 422)['detail']
    ok(api.delete(f"/records/{node['id']}"), 204)
    assert ok(api.put(f"/records/{node['id']}", json={'flags': 0}))['flags'] == 0   # un-delete


def test_types_are_searched_by_slug_in_every_schema(api):
    found = ok(api.get('/types', params={'filters': '{"slug": {"$eq": "node"}}'}))['items']
    assert [(t['slug'], t['shard']) for t in found] == [('node', 0x01)]
    cc = ok(api.get('/types', params={'filters': '{"slug": {"$eq": "cc"}}'}))['items']   # a file's type in fs, a session's in sessions
    assert sorted((UUID(t['id']).bytes[0], t['shard']) for t in cc) == [(0x10, 0x02), (0x20, 0x01)]


def test_the_file_system_is_in_its_own_schema(api):
    host = ok(api.post('/fs/locations', json={'type': 'host', 'status': 'active',
                                              'data': {'uid': 'root', 'canonical': 'file:///root', 'handler': {'kind': 'fileSystem'},
                                                       'provider': 'microsoft', 'service': 'windows'}}))
    file = ok(api.post('/fs/files', json={'type': 'markdown', 'parent_id': host['id'], 'name': 'a.md', 'data': {'extension': 'md'}}))
    instance = ok(api.post('/fs/instances', json={'type': 'instance', 'parent_id': file['id'], 'data': {'source': 'test', 'size': 3}}))
    node = ok(api.post('/records', json={'type': 'entity'}))
    link = ok(api.post('/fs/links', json={'type': 'link', 'from_id': host['id'], 'to_id': node['id']}))
    assert [header(r) for r in (host, file, instance, link)] == [bytes([0x10, s, 1]) + bytes(5) for s in (0x01, 0x02, 0x03, 0x10)]
    assert ok(api.get(f"/records/{file['id']}"))['type'] == 'markdown'   # every table inherits ld.records
    assert [l['id'] for l in ok(api.get(f"/records/{node['id']}/links"))['items']] == [link['id']]   # and every links table ld.links
    assert [t['slug'] for t in ok(api.get('/fs/types', params={'filters': '{"slug": {"$eq": "markdown"}}'}))['items']] == ['markdown']
    assert ok(api.post('/fs/locations', json={'type': 'location', 'provider': 'file_system'}), 422)['detail'][0]['loc'] == ['body', 'provider']


def test_a_session_is_known_by_its_type_and_uid(api):
    session = ok(api.post('/sessions', json={'type': 'cc', 'uid': 'u1', 'status': 'active', 'data': {'cwd': '/a'},
                                             'span': {'start': '2026-10-28T10:00:00Z', 'end': '2026-10-28T10:05:00Z'}}))
    again = ok(api.post('/sessions', json={'type': 'cc', 'uid': 'u1', 'status': 'completed', 'data': {'turns': 2}}))
    other = ok(api.post('/sessions', json={'type': 'cx', 'uid': 'u1'}))
    assert header(session) == bytes([0x20, 0x01, 1]) + bytes(5)
    assert again['id'] == session['id'] and again['status'] == 'completed' and again['data'] == {'cwd': '/a', 'turns': 2}
    assert other['id'] != session['id'] and ok(api.get(f"/sessions/{session['id']}"))['uid'] == 'u1'
    message = ok(api.post('/sessions/messages', json={'type': 'user', 'parent_id': session['id'], 'meta': {'uid': 'm1', 'line': 1}}))
    assert header(message)[:2] == bytes([0x20, 0x02])
    assert [m['id'] for m in ok(api.get(f"/records/{session['id']}/records"))] == [message['id']]
    nxt = ok(api.post('/sessions/links', json={'type': 'next', 'status': 'new', 'from_id': session['id'], 'to_id': other['id']}))
    assert header(nxt)[:2] == bytes([0x20, 0x10])
    assert [t['shard'] for t in ok(api.get('/sessions/types', params={'filters': '{"slug": {"$eq": "next"}}'}))['items']] == [0x10]


def test_a_sessions_messages_are_read_in_the_order_of_their_lines_a_page_at_a_time(api):
    session = ok(api.post('/sessions', json={'type': 'cx', 'uid': 'ordered'}))
    ids = sorted(uuid_create(0x20, 0x02) for _ in range(5))
    for id, line in zip(ids, (11, 10, 9, 2, 1)):   # the ids sort against the lines, and 10 and 11 sort before 9 and 2 as text
        ok(api.put(f'/sessions/messages/{id}', json={'type': 'agent', 'parent_id': session['id'], 'meta': {'line': line}}))
    lineless = ok(api.post('/sessions/messages', json={'type': 'user', 'parent_id': session['id']}))   # read as line 0
    read, cursor = [], None
    while True:
        page = ok(api.get(f"/ordered/{session['id']}/messages", params={'limit': 2} | ({'cursor': cursor} if cursor else {})))
        assert len(page['items']) <= 2 and page['total'] == 6
        read += [m['id'] for m in page['items']]
        if not (cursor := page['next']):
            break
    assert read == [lineless['id'], *map(str, reversed(ids))]


def pages(api, path: str, **params) -> list[dict]:
    """Every record a search finds, read a page at a time, each page after the cursor of the one before."""
    read, cursor = [], None
    while True:
        page = ok(api.get(path, params=params | ({'cursor': cursor} if cursor else {})))
        read += page['items']
        if not (cursor := page['next']):
            return read


def test_a_search_sorts_by_span_a_page_at_a_time_an_empty_span_least(api):
    starts = {'s1': '2026-10-28T10:00:00Z', 's2': '2026-10-28T12:00:00Z', 's3': None, 's4': '2026-10-28T11:00:00Z'}
    for uid, start in starts.items():
        ok(api.post('/sessions', json={'type': 'gemini', 'uid': uid} | ({'span': {'ts': start}} if start else {})))
    assert [s['uid'] for s in pages(api, '/sessions', type='gemini', sort='span:asc', limit=1)] == ['s3', 's1', 's4', 's2']
    assert [s['uid'] for s in pages(api, '/sessions', type='gemini', sort='span:desc', limit=1)] == ['s2', 's4', 's1', 's3']


def test_a_type_is_made_with_its_slug_and_shard_and_changed_without_them(api):
    made = ok(api.post('/types', json={'slug': 'testing', 'shard': 0x01, 'name': 'Testing'}))
    changed = ok(api.put(f"/types/{made['id']}", json={'data': {'x': 1}}))
    assert (changed['slug'], changed['shard'], changed['name'], changed['data']) == ('testing', 0x01, 'Testing', {'x': 1})
    assert '"slug"' in ok(api.post('/types', json={'shard': 0x01, 'name': 'No slug'}), 422)['detail']
    assert '"shard"' in ok(api.post('/types', json={'slug': 'no-shard', 'name': 'No shard'}), 422)['detail']


def test_a_link_is_written_with_its_relation_as_its_type(api):
    a, b = (ok(api.post('/records', json={'type': 'node'})) for _ in range(2))
    link = ok(api.post('/links', json={'type': 'implements', 'from_id': a['id'], 'to_id': b['id']}))
    assert ok(api.get(f"/links/{link['id']}"))['type'] == 'implements'


def test_gppufs_makes_its_catalog_from_the_locations(api):
    root = ok(api.post('/fs/locations', json={'type': 'host', 'status': 'active', 'name': 'Root',
                                              'data': {'uid': 'cat-root', 'canonical': 'file:///cat-root', 'handler': {'kind': 'fileSystem'}}}))
    ok(api.post('/fs/locations', json={'type': 'location', 'status': 'active', 'parent_id': root['id'], 'name': 'Inner',
                                       'data': {'uid': 'cat-inner', 'canonical': 'file:///cat-root/inner', 'tags': ['x']}}))
    ok(api.post('/fs/locations', json={'type': 'location', 'status': 'discarded', 'parent_id': root['id'],
                                       'data': {'uid': 'cat-discarded', 'canonical': 'file:///cat-root/discarded'}}))
    ok(api.post('/fs/locations', json={'type': 'location', 'parent_id': root['id'], 'flags': 16,
                                       'data': {'uid': 'cat-archived', 'canonical': 'file:///cat-root/archived'}}))
    catalog = locations.catalog(ok(api.get('/fs/locations'))['items'])
    assert {'cat-root', 'cat-inner'} <= catalog.locations.keys() and not {'cat-discarded', 'cat-archived'} & catalog.locations.keys()
    assert catalog.locations['cat-inner']['parent'] == 'cat-root' and catalog.locations['cat-inner']['tags'] == ['x']
