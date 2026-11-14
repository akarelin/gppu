"""gppu.fs.lake: an object saved without a uri is read by gppu's handlers, stored where the Lake's layout places it and recorded in
the Lake's catalog, answered with that uri and retrieved by it; a Lake folder is listed from the catalog, never from the store;
the Lake's API at /lake answers what the Lake answers itself. The catalog's database is conftest's ld, on LD_TEST_DSN."""
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime

import pytest

pytest.importorskip('fastapi')   # gppu's ld extra; the build's tests install gppu without it

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gppu import Env
from gppu.fs import DataObject, file_path
from gppu.fs.catalog import Catalog, GppuCatalog
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs.lake import Lake, LakeFileSystem, api

UID = '01c098c1-c196-49d4-b7e2-d2f544809574'
SESSION = '\n'.join(json.dumps(line) for line in (
    {'type': 'user', 'sessionId': UID, 'uuid': 'a1', 'timestamp': '2026-07-01T10:00:00Z',
     'message': {'role': 'user', 'content': 'hello'}},
    {'type': 'assistant', 'sessionId': UID, 'uuid': 'a2', 'parentUuid': 'a1', 'timestamp': '2026-07-01T10:01:00Z',
     'message': {'role': 'assistant', 'model': 'claude', 'content': [{'type': 'text', 'text': 'hi'}]}},
)) + '\n'
LAYOUT = {   # the Lake's lines: a session under timeseries, by its own start; an index under its host and folder
    'session': "timeseries/{{ start.year }}/Sessions/{{ '%02d' % start.month }}/{{ record.type }}/{{ record.uid }}/{{ name }}",
    'index': "indexes/{{ account }}/{{ path.rpartition('/')[0] | replace(':', '') }}/{{ name }}",
    'screenshot': "timeseries/{{ start.year }}/Screenshots/{{ '%02d' % start.month }}/{{ name }}",
    'shell': "timeseries/{{ start.year }}/Activity/Shell/{{ '%02d' % start.month }}/"
             "{{ start.strftime('%y%m%d.%H%M') }}_{{ stem.lstrip('.') }}_{{ host }}.txt",
}


@pytest.fixture(autouse=True)
def environment():
    """The Lake's lines where the Lake reads them, the environment's locations/lake/folders."""
    previous = Env._my
    Env._my = {'locations': {'lake': {'folders': LAYOUT}}}
    yield
    Env._my = previous


def lake_of(tmp_path, ld):
    """A Lake over one location, a folder holding a file and a folder with a note that the Lake did not save, its catalog on ld."""
    outer = tmp_path / 'outer'
    (outer / 'inner').mkdir(parents=True)
    (outer / 'a.txt').write_text('a')
    (outer / 'inner' / 'b.md').write_text('---\ntitle: B\n---\nText')
    catalog = GppuCatalog({'connections': {'file': {'provider': 'file'}},
                           'locations': {'outer': {'path': '', 'connection': 'file', 'canonical': outer.as_uri()}}})
    return Lake(catalog, outer.as_uri(), Catalog(lambda: [], ld)), outer


def test_a_session_is_placed_by_what_its_handler_reads_and_recorded_in_the_catalog(tmp_path, ld):
    lake, outer = lake_of(tmp_path, ld)
    uri = lake.save(DataObject('', SESSION.encode(), None, 'file', f'{UID}.jsonl'))
    placed = outer / 'timeseries' / '2026' / 'Sessions' / '07' / 'cc' / UID / f'{UID}.jsonl'
    assert str(uri) == placed.as_uri() and placed.read_text() == SESSION
    listed = lake.ls(placed.parent.as_uri())   # from the Lake's catalog
    assert [(row['name'], row['kind'], row['size']) for row in listed] == [(f'{UID}.jsonl', 'file', len(SESSION))]
    assert lake.info(uri)['type'] == 'cc'
    with lake.open(uri) as stream:
        assert stream.read() == SESSION.encode()
    assert not list(outer.rglob('*.gppufs.sqlite'))   # nothing but the file is written to the store


def test_a_file_path_is_the_line_for_its_type_filled_in_with_what_its_writer_knows(tmp_path):
    """No Lake and no catalog: a path generated and returned, no file touched."""
    session = tmp_path / f'{UID}.jsonl'
    session.write_text(SESSION)
    record = Lake.read(session)
    assert file_path('session', session.name, record=record, start=record.span.start) == \
        f'timeseries/2026/Sessions/07/cc/{UID}/{UID}.jsonl'
    assert file_path('index', '.Dev.gppufs.sqlite', account='alex-pc', path='D:/Dev/.Dev.gppufs.sqlite') == \
        'indexes/alex-pc/D/Dev/.Dev.gppufs.sqlite'
    assert file_path('screenshot', 'Screenshot 2026-11-10 101010.png', start=date(2026, 11, 10)) == \
        'timeseries/2026/Screenshots/11/Screenshot 2026-11-10 101010.png'
    assert file_path('shell', '.bash_history', start=datetime(2026, 11, 12, 9, 5), host='alex-pc') == \
        'timeseries/2026/Activity/Shell/11/261112.0905_bash_history_alex-pc.txt'
    assert not list(tmp_path.rglob('timeseries'))   # nothing written
    with pytest.raises(ValueError, match='no path for a file'):   # a type with no line
        file_path('file', 'Ann Lee.json', account='karelin', path='users/alex/contacts/Ann Lee.json')
    with pytest.raises(ValueError, match='no path'):   # a line asking for what it is not given
        file_path('session', session.name, record=record)


def test_an_object_the_layout_has_no_place_for_is_refused(tmp_path, ld):
    lake, _ = lake_of(tmp_path, ld)
    with pytest.raises(ValueError, match='no path'):
        lake.save(DataObject('', b'text', None, 'file', 'note.txt'))


def test_an_index_the_lake_receives_is_loaded_into_the_catalog_and_kept_with_the_files(tmp_path, ld):
    """FileIndexer sends each index a run wrote, named by the folder's uri: the Lake stores the index as any file, answers 202, and
    then loads it as that folder's latest copy; the catalog says which copy it received and whether it is loaded."""
    lake, outer = lake_of(tmp_path, ld)
    dev = tmp_path / 'Dev'
    (dev / 'sub').mkdir(parents=True)
    (dev / 'note.md').write_text('# note', encoding='utf-8')
    fs = GppuFileSystem()
    with fs.run():
        fs.ls(dev, recurse=True, refresh=True)
    index = dev / '.Dev.gppufs.sqlite'
    served = FastAPI()
    served.mount('/lake', api(lake))
    client = TestClient(served, raise_server_exceptions=False)
    sent = client.post('/lake/', params={'name': index.name, 'source': 'file://alex-pc/Dev/.Dev.gppufs.sqlite'}, content=index.read_bytes())
    assert sent.status_code == 202   # the load ran after the answer, as the test client runs a background task
    assert (outer / 'indexes' / 'alex-pc' / 'Dev' / '.Dev.gppufs.sqlite').read_bytes() == index.read_bytes()
    assert [row['name'] for row in lake.contents.entries(uri='file://alex-pc/Dev')] == ['note.md', 'sub']
    assert lake.info(sent.json()['uri'])['type'] == 'sqlite'
    state = lake.contents.loaded('file://alex-pc/Dev')
    assert state['loaded'] and state['received'] and not state['loading'] and state['error'] is None

    old = tmp_path / '.Old.gppufs.sqlite'   # an index written before gppufs gave its rows ids
    with closing(sqlite3.connect(old)) as db:
        db.execute('CREATE TABLE gppufs_entries (path TEXT PRIMARY KEY, metadata TEXT NOT NULL, children TEXT)')
        db.execute('INSERT INTO gppufs_entries (path, metadata) VALUES (?, ?)', ('.', json.dumps({'gppu': {'type': 'folder', 'handlers': ['folder']}})))
        db.commit()
    refused = client.post('/lake/', params={'name': old.name, 'source': 'file://alex-pc/Old/.Old.gppufs.sqlite'}, content=old.read_bytes())
    assert refused.status_code == 202 and refused.json()['uri'] in client.get('/lake/', params={'failed': ''}).json()
    state = lake.contents.loaded('file://alex-pc/Old')   # received, its load failed, nothing loaded
    assert state['loaded'] is None and not state['loading'] and state['error']


def test_the_api_at_lake_answers_what_the_lake_answers(tmp_path, ld):
    lake, outer = lake_of(tmp_path, ld)
    served = FastAPI()
    served.mount('/lake', api(lake))
    client = TestClient(served)
    saved = client.post('/lake/', params={'name': f'{UID}.jsonl'}, content=SESSION.encode())
    assert saved.status_code == 201 and saved.json()['uri'].endswith(f'/Sessions/07/cc/{UID}/{UID}.jsonl')
    top = outer.as_uri()
    listed = client.get(f'/lake/{top}', params={'ls': ''})
    assert listed.status_code == 200 and [row['name'] for row in listed.json()] == ['timeseries'] == [row['name'] for row in lake.ls(top)]
    assert client.get(f'/lake/{top}/a.txt', params={'content': ''}).content == b'a'   # the bytes of a file, from the store
    assert client.get('/lake/file://nowhere/x').status_code == 404
    assert client.get(f'/lake/{top}', params={'walk': ''}).status_code == 400   # the Lake is listed from its catalog, never walked
    taken = client.post('/lake/', params={'name': f'{UID}.jsonl'}, content=SESSION.replace('hello', 'other').encode())
    assert taken.status_code == 409 and 'error' in taken.json()
    unread = client.post('/lake/', params={'name': f'{UID}.jsonl'}, content=b'{"type": "user", "sessionId": "' + UID.encode() + b'"}\n')
    assert unread.status_code == 400 and 'gives no time' in unread.json()['error']   # a session with no time has no date to be placed by
    named = b''.join(json.dumps(line).encode() + b'\n' for line in (   # a session's first lines naming it, as preservator sent them
        {'type': 'custom-title', 'sessionId': UID, 'customTitle': 'x'}, {'type': 'ai-title', 'sessionId': UID, 'aiTitle': 'x'},
        {'type': 'permission-mode', 'sessionId': UID, 'permissionMode': 'default'}, {'type': 'file-history-snapshot', 'messageId': 'm'}))
    unplaced = client.post('/lake/', params={'name': f'{UID}.jsonl', 'copy': ''}, content=named)
    assert unplaced.status_code == 400 and unplaced.json()['error'] == (
        f'{UID}.jsonl: no path for a session: what was sent of it gives no time, so it has no date')
    assert client.post('/lake/', params={'name': 'note.txt'}, content=b'text').status_code == 400


def test_a_client_copies_a_session_where_the_lake_answers_then_has_it_indexed(tmp_path, ld):
    lake, outer = lake_of(tmp_path, ld)
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
    row = lake.info(placed.json()['uri'])   # from the Lake's catalog, recorded after the answer
    assert (row['type'], row['name'], row['size']) == ('cc', f'{UID}.jsonl', (outer / path).stat().st_size)
    (outer / path).write_text(SESSION + SESSION.splitlines(keepends=True)[1])   # the session's copy grows, and is indexed again
    assert client.post(f"/lake/{placed.json()['uri']}").status_code == 202
    again = lake.info(placed.json()['uri'])
    assert again['id'] == row['id'] and again['size'] > row['size']


def test_the_lake_answers_for_itself_and_keeps_a_failed_index(tmp_path, ld, monkeypatch):
    lake, outer = lake_of(tmp_path, ld)
    served = FastAPI()
    served.mount('/lake', api(lake))
    client = TestClient(served, raise_server_exceptions=False)   # an index fails after its 202, in the server's log
    copied = (outer / 'a.txt').as_uri()
    assert client.post(f'/lake/{copied}').status_code == 202
    assert client.get('/lake/').json() == json.loads(json.dumps(lake.info(outer.as_uri()), default=str))
    index = lake.index
    monkeypatch.setattr(lake, 'index', lambda uri: (_ for _ in ()).throw(ValueError('unreadable')))
    assert client.post(f'/lake/{copied}').status_code == 202
    assert client.get('/lake/', params={'failed': ''}).json() == {copied: 'ValueError: unreadable'}
    monkeypatch.setattr(lake, 'index', index)
    assert client.post(f'/lake/{copied}').status_code == 202
    assert client.get('/lake/', params={'failed': ''}).json() == {}


def test_the_lake_api_is_an_fsspec_filesystem(tmp_path, ld):
    lake, outer = lake_of(tmp_path, ld)
    for copied in (outer / 'a.txt', outer / 'inner' / 'b.md'):
        lake.index(copied.as_uri())
    served = FastAPI()
    served.mount('/lake', api(lake))
    fs = LakeFileSystem(root=outer.as_uri(), client=TestClient(served))
    assert sorted(fs.ls('', detail=False)) == ['a.txt', 'inner']
    assert fs.ls('inner', detail=False) == ['inner/b.md']
    assert fs.info('inner/b.md')['type'] == 'file' and fs.info('inner')['type'] == 'directory' and fs.cat_file('a.txt') == b'a'
    with pytest.raises(FileNotFoundError):
        fs.info('missing.txt')
    with pytest.raises(PermissionError):
        fs.open('a.txt', 'wb')


def test_the_lake_reaches_its_store_without_a_location_holding_it(tmp_path, ld):
    """The Lake's store is its own configuration: a Lake whose store no location of the catalog holds saves and retrieves there."""
    store = tmp_path / 'store'
    store.mkdir()
    lake = Lake(GppuCatalog({'connections': {}, 'locations': {}}), store.as_uri(), Catalog(lambda: [], ld))
    uri = lake.save(DataObject('', SESSION.encode(), None, 'file', f'{UID}.jsonl'))
    assert (store / 'timeseries' / '2026' / 'Sessions' / '07' / 'cc' / UID / f'{UID}.jsonl').read_text() == SESSION
    with lake.retrieve(uri).content as content, lake.open(uri) as opened:
        assert content.read() == opened.read() == SESSION.encode()
