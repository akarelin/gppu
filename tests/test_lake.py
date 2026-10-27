"""gppu.fs.lake: an object saved without a uri is read by gppu's handlers and stored where the Lake's layout places it, answered
with that uri and retrieved by it; the Lake's API at /lake answers what the Lake answers itself."""
import json

import pytest

pytest.importorskip('fastapi')   # gppu's ld extra; the build's tests install gppu without it

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gppu.fs import DataObject, GppuCatalog
from gppu.fs.lake import Lake, LakeFileSystem, api

UID = '01c098c1-c196-49d4-b7e2-d2f544809574'
SESSION = '\n'.join(json.dumps(line) for line in (
    {'type': 'user', 'sessionId': UID, 'uuid': 'a1', 'timestamp': '2026-07-01T10:00:00Z',
     'message': {'role': 'user', 'content': 'hello'}},
    {'type': 'assistant', 'sessionId': UID, 'uuid': 'a2', 'parentUuid': 'a1', 'timestamp': '2026-07-01T10:01:00Z',
     'message': {'role': 'assistant', 'model': 'claude', 'content': [{'type': 'text', 'text': 'hi'}]}},
)) + '\n'
LAYOUT = {   # the Lake's layout: a session under timeseries, by its own start; an original under its system and account
    'session': "timeseries/{{ start.year }}/Sessions/{{ '%02d' % start.month }}/{{ record.subtype }}/{{ record.uid }}/{{ name }}",
    'source': "{{ 'sources/' ~ system ~ '-' ~ account ~ '/' ~ path if system and account and path else '' }}",
}


def lake_of(tmp_path):
    """A Lake over one location, a folder holding a file and a folder with a note."""
    outer = tmp_path / 'outer'
    (outer / 'inner').mkdir(parents=True)
    (outer / 'a.txt').write_text('a')
    (outer / 'inner' / 'b.md').write_text('---\ntitle: B\n---\nText')
    catalog = GppuCatalog({'connections': {'file': {'provider': 'file'}},
                           'locations': {'outer': {'path': '', 'connection': 'file', 'canonical': outer.as_uri()}}})
    return Lake(catalog, outer.as_uri(), LAYOUT), outer


def test_a_session_is_placed_by_what_its_handler_reads(tmp_path):
    lake, outer = lake_of(tmp_path)
    uri = lake.save(DataObject('', SESSION.encode(), None, 'file', f'{UID}.jsonl'))
    placed = outer / 'timeseries' / '2026' / 'Sessions' / '07' / 'cc' / UID / f'{UID}.jsonl'
    assert str(uri) == placed.as_uri() and placed.read_text() == SESSION
    listed = lake.ls(placed.parent.as_uri())   # from the Lake's catalog, gppufs: named by uri, with what the handler read
    assert [row['name'] for row in listed] == [str(uri)] and listed[0]['gppu']['record']['subtype'] == 'cc'
    with lake.open(uri) as stream:
        assert stream.read() == SESSION.encode()


def test_an_original_is_placed_under_its_system_and_account(tmp_path):
    lake, outer = lake_of(tmp_path)
    uri = lake.save(DataObject('m365://karelin/users/alex/contacts/Ann%20Lee.json', b'{"a": 1}', None, 'file', 'Ann Lee.json'))
    assert str(uri) == (outer / 'sources' / 'm365-karelin' / 'users' / 'alex' / 'contacts' / 'Ann Lee.json').as_uri()


def test_an_object_the_layout_has_no_place_for_is_refused(tmp_path):
    lake, _ = lake_of(tmp_path)
    with pytest.raises(ValueError, match='no place'):
        lake.save(DataObject('', b'text', None, 'file', 'note.txt'))


def test_the_api_at_lake_answers_what_the_lake_answers(tmp_path):
    lake, outer = lake_of(tmp_path)
    served = FastAPI()
    served.mount('/lake', api(lake))
    client = TestClient(served)
    saved = client.post('/lake/', params={'name': f'{UID}.jsonl'}, content=SESSION.encode())
    assert saved.status_code == 201 and saved.json()['uri'].endswith(f'/Sessions/07/cc/{UID}/{UID}.jsonl')
    top = outer.as_uri()
    listed = client.get(f'/lake/{top}', params={'ls': ''})
    assert listed.status_code == 200 and [row['name'] for row in listed.json()] == [row['name'] for row in lake.ls(top)]
    assert client.get(f'/lake/{top}/a.txt', params={'content': ''}).content == b'a'
    assert client.get('/lake/file://nowhere/x').status_code == 404
    taken = client.post('/lake/', params={'name': f'{UID}.jsonl'}, content=SESSION.replace('hello', 'other').encode())
    assert taken.status_code == 409 and 'error' in taken.json()
    unread = client.post('/lake/', params={'name': f'{UID}.jsonl'}, content=b'{"type": "user", "sessionId": "' + UID.encode() + b'"}\n')
    assert unread.status_code == 400 and 'cannot read' in unread.json()['error']
    assert client.post('/lake/', params={'name': 'note.txt'}, content=b'text').status_code == 400


def test_a_client_copies_a_session_where_the_lake_answers_then_has_it_indexed(tmp_path):
    lake, outer = lake_of(tmp_path)
    served = FastAPI()
    served.mount('/lake', api(lake))
    client = TestClient(served)
    first = SESSION.splitlines(keepends=True)[0]   # as much of the session as its handler needs to place it
    placed = client.post('/lake/', params={'name': f'{UID}.jsonl', 'copy': ''}, content=first.encode())
    path = f'timeseries/2026/Sessions/07/cc/{UID}/{UID}.jsonl'
    assert placed.status_code == 200 and placed.json()['path'] == path and not (outer / path).exists()
    assert placed.json()['uri'] == (outer / path).as_uri()
    assert client.post(f"/lake/{placed.json()['uri']}").status_code == 404   # nothing copied there yet
    (outer / path).parent.mkdir(parents=True)
    (outer / path).write_text(SESSION)
    indexed = client.post(f"/lake/{placed.json()['uri']}")
    assert indexed.status_code == 202 and indexed.json()['uri'] == placed.json()['uri']
    row = lake.info(placed.json()['uri'])   # from the Lake's catalog, indexed after the answer
    assert row['gppu']['record']['subtype'] == 'cc' and row['gppu']['record']['uid'] == UID


def test_the_lake_answers_for_itself_and_keeps_a_failed_index(tmp_path, monkeypatch):
    lake, outer = lake_of(tmp_path)
    served = FastAPI()
    served.mount('/lake', api(lake))
    client = TestClient(served, raise_server_exceptions=False)   # an index fails after its 202, in the server's log
    assert client.get('/lake/').json() == json.loads(json.dumps(lake.info(outer.as_uri()), default=str))
    copied = (outer / 'a.txt').as_uri()
    index = lake.index
    monkeypatch.setattr(lake, 'index', lambda uri: (_ for _ in ()).throw(ValueError('unreadable')))
    assert client.post(f'/lake/{copied}').status_code == 202
    assert client.get('/lake/', params={'failed': ''}).json() == {copied: 'ValueError: unreadable'}
    monkeypatch.setattr(lake, 'index', index)
    assert client.post(f'/lake/{copied}').status_code == 202
    assert client.get('/lake/', params={'failed': ''}).json() == {}


def test_the_lake_api_is_an_fsspec_filesystem(tmp_path):
    lake, outer = lake_of(tmp_path)
    served = FastAPI()
    served.mount('/lake', api(lake))
    fs = LakeFileSystem(root=outer.as_uri(), client=TestClient(served))
    assert sorted(fs.ls('', detail=False)) == ['a.txt', 'inner']
    assert fs.info('inner/b.md')['type'] == 'file' and fs.cat_file('a.txt') == b'a'
    with pytest.raises(FileNotFoundError):
        fs.info('missing.txt')
    with pytest.raises(PermissionError):
        fs.open('a.txt', 'wb')
