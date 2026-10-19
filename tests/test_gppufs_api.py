"""gppu.fs.api: the Lake's /config and /lake as a FastAPI app answer what the Collection answers itself."""
import json

import pytest

pytest.importorskip('fastapi')   # gppu's ld extra; the build's tests install gppu without it

from fastapi.testclient import TestClient

from gppu.fs import Collection, GppuCatalog, _json, api


def lake_of(tmp_path):
    """A Lake of one configured Location, a folder holding a file and a folder with a note."""
    outer = tmp_path / 'outer'
    (outer / 'inner').mkdir(parents=True)
    (outer / 'a.txt').write_text('a')
    (outer / 'inner' / 'b.md').write_text('---\ntitle: B\n---\nText')
    rows = {'connections': {'file': {'provider': 'file'}},
            'locations': {'outer': {'id': 1, 'path': '', 'connection': 'file', 'canonical': outer.as_uri()}}}
    stored = []
    return Collection(lambda: GppuCatalog(rows), lambda *row: stored.append(row)), stored


def same(value):
    """A value as the app sends it, so it compares with what the app answered."""
    return json.loads(json.dumps(value, default=_json, ensure_ascii=False))


def test_config_and_lake_answer_what_the_collection_answers(tmp_path):
    lake, _ = lake_of(tmp_path)
    client = TestClient(api(lake))
    r = client.get('/config/locations')
    assert r.status_code == 200 and r.json() == same([location.data for location in lake.locations.values()])
    uid = next(iter(lake.locations))
    assert client.get(f'/config/locations/{uid}').json() == same(lake.location(uid).data)
    top = str(lake.location(uid).uri)
    listed = client.get(f'/lake/{top}', params={'ls': ''})
    assert listed.status_code == 200 and [row['name'] for row in listed.json()] == [row['name'] for row in lake.ls(top)]
    assert client.get(f'/lake/{top}').json()['name'] == lake.info(top)['name']


def test_an_unknown_location_answers_404(tmp_path):
    lake, _ = lake_of(tmp_path)
    r = TestClient(api(lake)).get('/config/locations/no-such-uid')
    assert r.status_code == 404 and 'error' in r.json()
