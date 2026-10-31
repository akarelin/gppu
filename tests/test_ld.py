"""gppu.ld, gppu.fs.files and gppu.ld.sessions on Postgres: the standard's schemas ld, fs and sessions (tests/ld.sql) in a database
of their own, made for these tests and dropped after them; every call goes through the API to Postgres and back. LD_TEST_DSN is the
Postgres server to make it on."""
import asyncio
import json
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
from gppu.fs import files
from gppu.ld import Page, Params, api_at, serve, sessions

DSN = os.environ['LD_TEST_DSN']
DB = f'gppu_ld_test_{uuid4().hex[:12]}'   # its own, so no other database on the server is touched
STORE = DSN.rsplit('/', 1)[0] + '/' + DB
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
    previous, initialized = Env.data, Env.initialized
    try:
        with psycopg.connect(STORE, autocommit=True) as db:
            db.execute((Path(__file__).parent / 'ld.sql').read_text(encoding='utf-8'))
        Env._load_dict({'db': STORE})   # the store's `db`, as an app's configuration gives it
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


def links_of(record) -> str:
    """The filter of a record's links, from it and to it."""
    return json.dumps({'$or': [{'from_id': {'$eq': record['id']}}, {'to_id': {'$eq': record['id']}}]})


def header(record) -> bytes:
    """An id's first eight bytes: shard1, shard2, version 1 and five reserved bytes of 0."""
    return UUID(record['id']).bytes[:8]


def test_a_record_is_made_in_the_table_of_its_path(api):
    node = ok(api.post('/nodes', json={'type': 'node', 'data': {'x': 1}}))
    entity = ok(api.post('/nodes', json={'type': 'entity'}))
    activity = ok(api.post('/events', json={'type': 'activity', 'span': {'start': '2026-10-27T10:00:00Z', 'end': '2026-10-27T11:00:00Z'}}))
    event = ok(api.post('/events', json={'type': 'event'}))
    assert header(node) == header(entity) == bytes([0x00, 0x01, 1]) + bytes(5)
    assert header(activity) == header(event) == bytes([0x00, 0x20, 1]) + bytes(5)
    assert node['flags'] == 0 and 'name' not in node and node['status'] is None and node['kind'] is None
    assert activity['ts'].startswith('2026-10-27T10:00:00')


def test_the_store_fills_its_own_columns(api):
    for column, value in (('ts', '2026-10-27T10:00:00Z'), ('status', 'active'), ('kind', 'chore')):
        assert 'the store fills them' in ok(api.post('/nodes', json={'type': 'node', column: value}), 422)['detail']
    assert ok(api.post('/nodes', json={'type': 'node', 'name': 'A name'}), 422)['detail'][0]['loc'] == ['body', 'name']


def test_a_records_status_and_kind_are_its_metas(api):
    task = ok(api.post('/nodes', json={'type': 'task', 'meta': {'status': 'proposed', 'kind': 'chore', 'display_name': 'A chore'}}))
    assert (task['status'], task['kind'], task['meta']['display_name']) == ('proposed', 'chore', 'A chore')
    changed = ok(api.put(f"/nodes/{task['id']}", json={'meta': {'status': 'active', 'kind': 'problem'}}))
    assert (changed['status'], changed['kind'], changed['meta']['display_name']) == ('active', 'problem', 'A chore')
    found = ok(api.get('/nodes', params={'filters': json.dumps({'kind': {'$eq': 'problem'}, 'status': {'$eq': 'active'}})}))['items']
    assert [x['id'] for x in found] == [task['id']]
    assert ok(api.put(f"/nodes/{task['id']}", json={'meta': {'kind': None}}))['kind'] is None


def test_a_key_of_meta_is_filtered_sorted_and_searched_as_a_column_is(api):
    parent = ok(api.post('/nodes', json={'type': 'project', 'meta': {'display_name': 'Named things'}}))
    for name in ('beta', 'Alpha', None, 'gamma'):
        ok(api.post('/nodes', json={'type': 'task', 'parent_id': parent['id']} | ({'meta': {'display_name': name}} if name else {})))
    under = {'parent_id': {'$eq': parent['id']}}
    named = lambda **params: [t['meta'].get('display_name') for t in pages(api, '/nodes', **params)]
    assert named(filters=json.dumps(under), sort='meta.display_name:asc', limit=1) == [None, 'Alpha', 'beta', 'gamma']   # one without a name is least
    assert named(filters=json.dumps(under), sort='meta.display_name:desc', limit=1) == ['gamma', 'beta', 'Alpha', None]
    assert named(filters=json.dumps(under | {'meta.display_name': {'$startswith': 'g'}})) == ['gamma']
    assert named(filters=json.dumps({'$or': [{'meta.display_name': {'$eq': 'alpha'}}, {'meta.display_name': {'$eq': 'Beta'}}]})) == ['beta', 'Alpha']
    assert named(search='named thing') == ['Named things']
    assert 'no column' in ok(api.get('/nodes', params={'filters': json.dumps({'name': {'$eq': 'x'}})}), 400)['detail']


def test_abandoned_comes_with_archived_and_rejected_with_deleted(api):
    work = ok(api.post('/nodes', json={'type': 'task', 'meta': {'status': 'proposed'}}))
    abandoned = ok(api.put(f"/nodes/{work['id']}", json={'meta': {'status': 'abandoned'}}))
    assert (abandoned['status'], abandoned['flags']) == ('abandoned', 16) and ok(api.get(f"/nodes/{work['id']}"))['flags'] == 16
    assert ok(api.put(f"/nodes/{work['id']}", json={'flags': 0}))['flags'] == 0   # un-archive keeps the status it has
    rejected = ok(api.post('/nodes', json={'type': 'task', 'meta': {'status': 'rejected'}}))
    assert rejected['flags'] == 4 and ok(api.get(f"/nodes/{rejected['id']}"))['flags'] == 4


def test_an_update_merges_data_and_a_null_removes_a_key(api):
    node = ok(api.post('/nodes', json={'type': 'node', 'data': {'a': 1, 'b': 2}}))
    updated = ok(api.put(f"/nodes/{node['id']}", json={'data': {'b': None, 'c': 3}}))
    assert updated['data'] == {'a': 1, 'c': 3} and updated['updated']


def test_a_put_of_an_id_not_there_creates_it(api):
    id = uuid_create(0x0001)   # made offline as the store makes them
    assert ok(api.put(f'/nodes/{id}', json={'type': 'node'}))['id'] == str(id)
    assert ok(api.get(f'/nodes/{id}'))['type'] == 'node'
    assert 'no record' in ok(api.put(f'/nodes/{uuid_create(0x0020)}', json={'type': 'node'}), 422)['detail']   # an id of another table


def test_a_link_joins_two_records(api):
    a, b = (ok(api.post('/nodes', json={'type': 'node'})) for _ in range(2))
    link = ok(api.post('/links', json={'type': 'link', 'from_id': a['id'], 'to_id': b['id']}))
    assert header(link)[:2] == bytes([0x00, 0x10])
    assert [l['id'] for l in ok(api.get('/links', params={'filters': links_of(a)}))['items']] == [link['id']]


def test_a_read_only_record_changes_only_its_flags(api):
    node = ok(api.post('/nodes', json={'type': 'node', 'flags': 1}))
    assert 'read only' in ok(api.put(f"/nodes/{node['id']}", json={'data': {'a': 1}}), 422)['detail']
    assert ok(api.put(f"/nodes/{node['id']}", json={'flags': 0}))['flags'] == 0
    assert ok(api.put(f"/nodes/{node['id']}", json={'data': {'a': 1}}))['data'] == {'a': 1}


def test_a_read_only_type_is_neither_changed_nor_deleted_by_the_api_or_in_the_database(api):
    kept = ok(api.post('/types', json={'slug': 'kept', 'shard': 0x0001, 'meta': {'display_name': 'Kept'}}))
    assert ok(api.put(f"/types/{kept['id']}", json={'flags': 1}))['flags'] == 1   # toggle ro
    assert 'read only' in ok(api.put(f"/types/{kept['id']}", json={'data': {'a': 1}}), 422)['detail']
    assert 'change only by toggle ro' in ok(api.delete(f"/types/{kept['id']}"), 422)['detail']
    with psycopg.connect(STORE, autocommit=True) as db:
        with pytest.raises(psycopg.errors.RaiseException, match='only its flags change'):
            db.execute("UPDATE ld.types SET data = '{\"a\": 1}' WHERE id = %s", (kept['id'],))
        with pytest.raises(psycopg.errors.RaiseException, match='it is not deleted'):
            db.execute('DELETE FROM ld.types WHERE id = %s', (kept['id'],))
    assert ok(api.put(f"/types/{kept['id']}", json={'flags': 0}))['flags'] == 0   # toggle ro, and it changes again
    assert ok(api.put(f"/types/{kept['id']}", json={'data': {'a': 1}}))['data'] == {'a': 1}


def test_a_deleted_record_is_out_of_sight_and_read_by_its_id(api):
    parent = ok(api.post('/nodes', json={'type': 'node'}))
    child = ok(api.post('/nodes', json={'type': 'node', 'parent_id': parent['id']}))
    hidden = ok(api.post('/nodes', json={'type': 'node', 'parent_id': parent['id'], 'flags': 8}))
    ok(api.delete(f"/nodes/{child['id']}"), 204)
    assert ok(api.get(f"/nodes/{child['id']}"))['flags'] == 4
    assert ok(api.get('/nodes', params={'filters': json.dumps({'parent_id': {'$eq': parent['id']}})}))['total'] == 0
    assert ok(api.get(f"/nodes/{hidden['id']}"))['flags'] == 8
    assert 'read only' in ok(api.put(f"/nodes/{child['id']}", json={'data': {'a': 1}}), 422)['detail']
    under = {'parent_id': {'$eq': parent['id']}}
    asked = lambda *more: sorted(r['id'] for r in ok(api.get('/nodes', params={'filters': json.dumps({'$and': [under, *more]})}))['items'])
    assert asked({'flags': {'$gte': 0}}) == sorted([child['id'], hidden['id']])   # out of sight when the filters ask for flags
    assert asked({'$or': [{'flags': {'$eq': 4}}]}) == [child['id']]


def test_flags_change_only_by_their_transitions(api):
    node = ok(api.post('/nodes', json={'type': 'node'}))
    assert 'change only by delete, archive, toggle hidden, toggle ro' in ok(api.put(f"/nodes/{node['id']}", json={'flags': 3}), 422)['detail']
    assert ok(api.put(f"/nodes/{node['id']}", json={'flags': 16}))['flags'] == 16   # archive
    assert 'change only by un-archive' in ok(api.put(f"/nodes/{node['id']}", json={'flags': 20}), 422)['detail']
    assert 'change only by un-archive' in ok(api.delete(f"/nodes/{node['id']}"), 422)['detail']
    assert ok(api.put(f"/nodes/{node['id']}", json={'flags': 0}))['flags'] == 0   # un-archive
    hidden = ok(api.post('/nodes', json={'type': 'node', 'flags': 8}))
    assert 'change only by toggle hidden' in ok(api.delete(f"/nodes/{hidden['id']}"), 422)['detail']
    system = ok(api.post('/nodes', json={'type': 'node', 'flags': 2}))
    assert 'no transition' in ok(api.put(f"/nodes/{system['id']}", json={'flags': 0}), 422)['detail']
    ok(api.delete(f"/nodes/{node['id']}"), 204)
    assert ok(api.put(f"/nodes/{node['id']}", json={'flags': 0}))['flags'] == 0   # un-delete


def types(api, path: str, **filters) -> list[dict]:
    """The rows of a schema's types whose columns have these values."""
    return ok(api.get(path, params={'filters': json.dumps({k: {'$eq': v} for k, v in filters.items()})}))['items']


def test_each_schema_defines_its_own_types_and_values(api):
    assert [(t['slug'], t['shard']) for t in types(api, '/types', slug='node')] == [('node', 0x0001)]
    assert types(api, '/types', slug='cc') == types(api, '/fs/types', slug='cc') == []
    cc, = types(api, '/sessions/types', slug='cc')
    harness, = types(api, '/sessions/types', slug='harness')
    assert (cc['shard'], cc['parent_id'], cc['kind'], cc['meta']['uri']) == (0x2000, harness['id'], 'session', 'uo:HarnessClaudeCode')
    status, = [t for t in types(api, '/types', slug='status') if t['meta'].get('uri') == 'uo:Status']
    parsed, = types(api, '/fs/types', slug='parsed')
    assert (parsed['parent_id'], parsed['kind']) == (status['id'], 'file')   # a value of the core's vocabulary, for an fs type
    assert {t['slug'] for t in types(api, '/types', parent_id=status['id'])} == {'proposed', 'active', 'rejected', 'pending', 'planned', 'suspended', 'abandoned', 'completed'}
    assert [t['shard'] for t in types(api, '/types', slug='next')] == [0x0010]   # every schema's links take the core's link types


def test_a_slug_is_one_under_its_parent(api):
    status, = [t for t in types(api, '/types', slug='status') if t['meta'].get('uri') == 'uo:Status']
    meta, = types(api, '/types', slug='meta')
    assert {t['parent_id'] for t in types(api, '/types', slug='status')} == {meta['id'], status['parent_id']}   # a key of meta and a vocabulary
    ok(api.post('/types', json={'slug': 'active', 'shard': 0, 'parent_id': status['id'], 'meta': {'kind': 'node'}}), 422)
    ok(api.post('/types', json={'slug': 'active', 'shard': 0, 'parent_id': meta['id']}))


def test_the_file_system_is_in_its_own_schema(api):
    host = ok(api.post('/fs/locations', json={'type': 'host', 'meta': {'status': 'active', 'uri': 'file:///root'}}))
    file = ok(api.post('/fs/files', json={'type': 'markdown', 'parent_id': host['id'], 'meta': {'display_name': 'a.md'}, 'data': {'extension': 'md'}}))
    instance = ok(api.post('/fs/instances', json={'type': 'instance', 'parent_id': file['id'], 'meta': {'kind': 'symlink'}, 'data': {'source': 'test', 'size': 3}}))
    node = ok(api.post('/nodes', json={'type': 'entity'}))
    link = ok(api.post('/fs/links', json={'type': 'link', 'from_id': host['id'], 'to_id': node['id']}))
    assert [header(r) for r in (host, file, instance, link)] == [bytes([0x10, s, 1]) + bytes(5) for s in (0x01, 0x02, 0x03, 0x10)]
    assert ok(api.get(f"/fs/files/{file['id']}"))['type'] == 'markdown' and instance['kind'] == 'symlink' and host['status'] == 'active'
    assert [l['id'] for l in ok(api.get('/fs/links', params={'filters': links_of(node)}))['items']] == [link['id']]
    assert ok(api.get('/links', params={'filters': links_of(node)}))['items'] == []   # each schema's links are its own
    assert [t['slug'] for t in types(api, '/fs/types', slug='session-file')] == ['session-file']
    assert ok(api.post('/fs/locations', json={'type': 'location', 'provider': 'file_system'}), 422)['detail'][0]['loc'] == ['body', 'provider']


def test_a_session_is_known_by_its_harness_and_uid(api):
    session = ok(api.post('/sessions', json={'type': 'session', 'meta': {'harness': 'cc', 'uid': 'u1', 'status': 'active'}, 'data': {'cwd': '/a'},
                                             'span': {'start': '2026-10-28T10:00:00Z', 'end': '2026-10-28T10:05:00Z'}}))
    again = ok(api.post('/sessions', json={'type': 'session', 'meta': {'harness': 'cc', 'uid': 'u1', 'status': 'completed'}, 'data': {'turns': 2}}))
    other = ok(api.post('/sessions', json={'type': 'session', 'meta': {'harness': 'cx', 'uid': 'u1'}}))
    assert header(session) == bytes([0x20, 0x01, 1]) + bytes(5)
    assert again['id'] == session['id'] and again['status'] == 'completed' and again['data'] == {'cwd': '/a', 'turns': 2}
    assert other['id'] != session['id'] and ok(api.get(f"/sessions/{session['id']}"))['meta']['uid'] == 'u1'
    message = ok(api.post('/sessions/messages', json={'type': 'message', 'parent_id': session['id'], 'meta': {'kind': 'user', 'uid': 'm1', 'line': 1}}))
    assert header(message)[:2] == bytes([0x20, 0x02]) and message['kind'] == 'user'
    children = {'filters': json.dumps({'parent_id': {'$eq': session['id']}})}
    assert [m['id'] for m in ok(api.get('/sessions/messages', params=children))['items']] == [message['id']]
    nxt = ok(api.post('/sessions/links', json={'type': 'next', 'meta': {'status': 'proposed'}, 'from_id': session['id'], 'to_id': other['id']}))
    assert header(nxt)[:2] == bytes([0x20, 0x10]) and nxt['status'] == 'proposed'
    by = lambda **keys: [s['id'] for s in ok(api.get('/sessions', params={'filters': json.dumps({f'meta.{k}': {'$eq': v} for k, v in keys.items()})}))['items']]
    assert by(harness='cx', uid='u1') == [other['id']] and session['id'] in by(harness='cc')


def test_a_sessions_messages_are_read_in_the_order_of_their_lines_a_page_at_a_time(api):
    session = ok(api.post('/sessions', json={'type': 'session', 'meta': {'harness': 'cx', 'uid': 'ordered'}}))
    ids = sorted(uuid_create(0x2002) for _ in range(5))
    for id, line in zip(ids, (11, 10, 9, 2, 1)):   # the ids sort against the lines, and 10 and 11 sort before 9 and 2 as text
        ok(api.put(f'/sessions/messages/{id}', json={'type': 'message', 'parent_id': session['id'], 'meta': {'kind': 'assistant', 'line': line}}))
    lineless = ok(api.post('/sessions/messages', json={'type': 'message', 'parent_id': session['id'], 'meta': {'kind': 'user'}}))   # read as line 0
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
    parent = ok(api.post('/sessions', json={'type': 'session', 'meta': {'harness': 'gemini', 'uid': 'spans'}}))
    starts = {'s1': '2026-10-28T10:00:00Z', 's2': '2026-10-28T12:00:00Z', 's3': None, 's4': '2026-10-28T11:00:00Z'}
    for uid, start in starts.items():
        ok(api.post('/sessions', json={'type': 'session', 'parent_id': parent['id'], 'meta': {'harness': 'gemini', 'uid': uid}} | ({'span': {'ts': start}} if start else {})))
    under = json.dumps({'parent_id': {'$eq': parent['id']}})
    assert [s['meta']['uid'] for s in pages(api, '/sessions', filters=under, sort='span:asc', limit=1)] == ['s3', 's1', 's4', 's2']
    assert [s['meta']['uid'] for s in pages(api, '/sessions', filters=under, sort='span:desc', limit=1)] == ['s2', 's4', 's1', 's3']


def test_a_type_is_made_with_its_slug_and_shard_and_changed_without_them(api):
    made = ok(api.post('/types', json={'slug': 'testing', 'shard': 0x0001, 'meta': {'display_name': 'Testing'}}))
    changed = ok(api.put(f"/types/{made['id']}", json={'data': {'x': 1}}))
    assert (changed['slug'], changed['shard'], changed['meta'], changed['data']) == ('testing', 0x0001, {'display_name': 'Testing'}, {'x': 1})
    assert '"slug"' in ok(api.post('/types', json={'shard': 0x0001}), 422)['detail']
    assert '"shard"' in ok(api.post('/types', json={'slug': 'no-shard'}), 422)['detail']


def test_a_link_is_written_with_its_relation_as_its_type(api):
    a, b = (ok(api.post('/nodes', json={'type': 'node'})) for _ in range(2))
    link = ok(api.post('/links', json={'type': 'implements', 'from_id': a['id'], 'to_id': b['id']}))
    assert ok(api.get(f"/links/{link['id']}"))['type'] == 'implements'


def test_gppufs_makes_its_catalog_from_the_locations(api):
    root = ok(api.post('/fs/locations', json={'type': 'host', 'meta': {'status': 'active', 'display_name': 'Root', 'uri': 'file:///cat-root'}}))
    inner = ok(api.post('/fs/locations', json={'type': 'location', 'parent_id': root['id'], 'meta': {'status': 'active', 'display_name': 'Inner', 'uri': 'file:///cat-root/inner'},
                                               'data': {'tags': ['x']}}))
    archived = ok(api.post('/fs/locations', json={'type': 'location', 'parent_id': root['id'], 'flags': 16,
                                                  'meta': {'uri': 'file:///cat-root/archived'}}))
    catalog = locations.catalog(ok(api.get('/fs/locations'))['items'])
    assert {root['id'], inner['id']} <= catalog.locations.keys() and archived['id'] not in catalog.locations
    assert catalog.locations[inner['id']]['parent'] == root['id'] and catalog.locations[inner['id']]['tags'] == ['x']
