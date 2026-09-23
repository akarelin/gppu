import json

import pytest

from gppu import DataObject, FileLocation, Location, y2path, y2uri
from gppu.providers import FileContainer, M365Container


@pytest.mark.parametrize('value', [
  'file:///', 'file:///D:/folder/name%20with%20space', 'file://server/share/',
  'm365://tenant/users/alex/contacts/id%2Fpart', 'plaud://',
])
def test_uri_round_trip(value):
  uri = y2uri(value)
  assert isinstance(uri.path, y2path)
  assert y2uri(uri.scheme, uri.path) == value
  assert json.loads(json.dumps({'uri': uri})) == {'uri': value}


@pytest.mark.parametrize('root, expected', [
  ('file:///', 'file:///folder/item'),
  ('file:///D:/', 'file:///D:/folder/item'),
  ('m365://tenant/', 'm365://tenant/folder/item'),
  ('plaud://', 'plaud://folder/item'),
])
def test_uri_path_operators(root, expected):
  uri = y2uri(root)
  for joined in (uri / y2path('folder/item'), uri + y2path('folder/item'),
                 uri / 'folder' / 'item', uri + '/folder/' + 'item'):
    assert isinstance(joined, y2uri)
    assert joined == expected
  assert uri / '' == uri
  assert uri / 'id%2Fpart' == expected.removesuffix('folder/item') + 'id%2Fpart'
  with pytest.raises(ValueError):
    uri / 'file:///other'


@pytest.mark.parametrize('value', ['', 'folder/item', '1bad://path'])
def test_uri_requires_scheme(value):
  with pytest.raises(ValueError):
    y2uri(value)


def test_location_and_file_container_use_types(tmp_path):
  (tmp_path / 'folder').mkdir()
  (tmp_path / 'folder' / 'item.json').write_text('{"value": true}')
  location = FileLocation({'uid': 'test', 'canonical': tmp_path.as_uri()})
  assert isinstance(location.uri, y2uri)
  assert isinstance(Location.relative('folder'), y2path)
  assert location.address(y2path('name #%.json')).endswith('/name%20%23%25.json')
  container = location.container(y2path('folder'))
  assert isinstance(container.uri, y2uri)
  assert container.ls(y2path(), detail=False) == ['item.json']
  obj = container.read(y2path('item.json'))
  assert isinstance(obj.uri, y2uri)
  assert obj.content == {'value': True}
  assert obj.identity == 'item.json'
  assert list(container.walk(y2path()))[0][1][0]['name'] == 'item.json'
  state = {}
  with container.refresh(state, y2path()) as objects:
    assert all(isinstance(item.uri, y2uri) for item in objects)
  container.delete(y2path('item.json'))
  assert container.ls() == []
  with pytest.raises(ValueError):
    location.container(y2path('..'))


def test_m365_container_keeps_typed_paths_and_source_uris():
  class Source:
    _namespace = 'm365://tenant'

    def _each(self, endpoint):
      if endpoint.endswith('/contacts'):
        return [{'id': 'id/part', 'displayName': 'Name'}]
      return []

    def _get(self, endpoint):
      return {'id': 'id/part', 'displayName': 'Name'}

  container = M365Container(Source(), 'alex', 'contacts', y2path(),
    y2uri('m365://tenant/users/alex/contacts'))
  assert isinstance(container.path, y2path)
  assert isinstance(container.uri, y2uri)
  assert container.ls(y2path(), detail=False) == ['id%2Fpart']
  obj = container.read(y2path('id%2Fpart'))
  assert isinstance(obj.uri, y2uri)
  assert obj.uri == 'm365://tenant/users/alex/contacts/id%2Fpart'


def test_dataobject_constructs_uri_type():
  obj = DataObject('file:///data/item', {}, 'item')
  assert isinstance(obj.uri, y2uri)
  assert isinstance(obj.uri / y2path('child'), y2uri)


def test_file_write_reads_typed_source_uri_in_template(tmp_path):
  container = FileContainer(tmp_path, templates={'filename': '{{ uri.path.tail }}.json'})
  obj = DataObject(y2uri('m365://tenant') / y2path('item'), {'value': True}, 'item')
  container.write(obj)
  assert container.read(y2path('item.json')).content == obj.content
  assert container.read(obj).uri == obj.uri
  container.delete(obj)
  assert container.ls() == []
