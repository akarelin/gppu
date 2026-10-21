"""gppu.lake: an object saved without a uri is stored where the Lake places it and answered with that uri, and is retrieved by it;
the Lake's API at /lake answers what the Lake answers itself."""
import pytest

pytest.importorskip('fastapi')   # gppu's ld extra; the build's tests install gppu without it

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gppu.fs import DataObject, GppuCatalog
from gppu.lake import Lake, api


def lake_of(tmp_path):
    """A Lake over one location, a folder holding a file and a folder with a note, saving into its inbox by the object's name."""
    outer = tmp_path / 'outer'
    (outer / 'inner').mkdir(parents=True)
    (outer / 'inbox').mkdir()
    (outer / 'a.txt').write_text('a')
    (outer / 'inner' / 'b.md').write_text('---\ntitle: B\n---\nText')
    catalog = GppuCatalog({'connections': {'file': {'provider': 'file'}},
                           'locations': {'outer': {'path': '', 'connection': 'file', 'canonical': outer.as_uri()}}})
    return Lake(catalog, (outer / 'inbox').as_uri(), {'filename': '{{ filename }}'}), outer


def test_a_saved_object_is_retrieved_by_the_uri_the_lake_gives(tmp_path):
    lake, outer = lake_of(tmp_path)
    uri = lake.save(DataObject('', b'saved blindly', None, 'file', 'note.txt'))
    assert str(uri) == (outer / 'inbox' / 'note.txt').as_uri()
    assert (outer / 'inbox' / 'note.txt').read_bytes() == b'saved blindly'
    with lake.open(uri) as stream:
        assert stream.read() == b'saved blindly'


def test_the_api_at_lake_answers_what_the_lake_answers(tmp_path):
    lake, outer = lake_of(tmp_path)
    served = FastAPI()
    served.mount('/lake', api(lake))
    client = TestClient(served)
    saved = client.post('/lake/', json={'content': {'text': 'posted'}, 'name': 'posted.json'})
    assert saved.status_code == 201 and saved.json()['uri'] == (outer / 'inbox' / 'posted.json').as_uri()
    top = outer.as_uri()
    listed = client.get(f'/lake/{top}', params={'ls': ''})
    assert listed.status_code == 200 and [row['name'] for row in listed.json()] == [row['name'] for row in lake.ls(top)]
    assert client.get(f'/lake/{top}/inbox/posted.json', params={'retrieve': ''}).json()['content'] == {'text': 'posted'}
    assert client.get('/lake/file://nowhere/x').status_code == 404
