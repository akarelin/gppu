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
  assert y2uri(uri.path, scheme=uri.scheme) == value
  assert json.loads(json.dumps({'uri': uri.to_json()})) == {'uri': value}


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
  with pytest.raises(ValueError):
    uri / 'child?query=value'


@pytest.mark.parametrize('value', ['', '1bad://path'])
def test_uri_requires_scheme(value):
  with pytest.raises(ValueError):
    y2uri(value)


def test_location_and_file_container_use_types(tmp_path):
  (tmp_path / 'folder').mkdir()
  (tmp_path / 'folder' / 'item.json').write_text('{"value": true}')
  location = FileLocation({'uid': 'test', 'canonical': tmp_path.as_uri()})
  assert isinstance(location.uri, y2uri)
  assert isinstance(Location.relative('folder'), y2path)
  assert location.address(y2path('name #%.json')).path.tail == 'name%20%23%25.json'
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


def test_uri_mutation_updates_representation_comparison_and_joins():
  uri = y2uri('file://host/folder')
  path = uri.path
  uri.scheme = 'xxx'
  path.append('item')
  assert uri.path is path
  assert isinstance(path, y2path)
  assert str(uri) == 'xxx://host/folder/item'
  assert uri == 'xxx://host/folder/item'
  assert 'xxx://host/folder/item' == uri
  assert uri != 'file://host/folder'
  assert uri < 'xxx://host/folder/z'
  assert uri <= y2uri(str(uri))
  assert uri > 'aaa://host'
  assert uri >= y2uri(str(uri))
  assert {uri: 'found'}[str(uri)] == 'found'
  assert len({uri, y2uri(str(uri)), str(uri)}) == 1
  assert uri / 'child' == 'xxx://host/folder/item/child'
  assert uri + y2path('child') == uri / 'child'
  copied = y2uri(uri)
  joined = uri / ''
  copied.path.append('copy')
  joined.scheme = 'other'
  assert str(uri) == 'xxx://host/folder/item'
  uri.path = y2path('replacement')
  assert str(uri) == 'xxx://replacement'


def test_uri_mutable_query_parameters_and_path_joins():
  uri = y2uri('https://host/folder?q=hello+world&empty=&tag=a&tag=b#section')
  assert str(uri.path) == 'host/folder'
  assert uri.params == {'q': 'hello world', 'empty': '', 'tag': ['a', 'b']}
  uri.scheme = 'xxx'
  uri.params['q'] = 'a&b?c/é'
  uri.path.append('item')
  assert str(uri) == 'xxx://host/folder/item?q=a%26b%3Fc%2F%C3%A9&empty=&tag=a&tag=b#section'
  for joined in (uri / y2path('child'), uri + 'child'):
    assert str(joined.path) == 'host/folder/item/child'
    assert joined.params == uri.params
    assert joined.fragment == 'section'
    joined.params['tag'].append('c')
    assert uri.params['tag'] == ['a', 'b']
  copied = y2uri(uri)
  copied.params['q'] = 'changed'
  assert copied != uri
  uri.params = {'page': '2'}
  assert str(uri).endswith('?page=2#section')
  uri.params.clear()
  assert str(uri) == 'xxx://host/folder/item#section'


def test_uri_scheme_path_and_parameter_dictionary():
  uri = y2uri(y2path('host/items'), scheme='https')
  uri.params = {'q': 'a b', 'empty': ''}
  assert str(uri) == 'https://host/items?q=a+b&empty='
  assert y2uri(str(uri)).params == uri.params


def test_uri_query_and_fragment_instance_access():
  import inspect
  assert list(inspect.signature(y2uri).parameters) == ['o', 'scheme']
  uri = y2uri('https://host/path?key=first#section')
  assert uri.query == 'key=first'
  assert uri.fragment == 'section'
  uri.query = 'tag=a&tag=b&empty=&q=hello%20world'
  assert uri.params == {'tag': ['a', 'b'], 'empty': '', 'q': 'hello world'}
  uri.params['q'] = 'other'
  uri.fragment = 'next'
  assert str(uri) == 'https://host/path?tag=a&tag=b&empty=&q=other#next'
  joined = uri / 'child'
  assert joined.query == uri.query
  assert joined.fragment == 'next'
  uri.query = ''
  uri.fragment = ''
  assert uri.params == {}
  assert str(uri) == 'https://host/path'


def test_uri_endswith_checks_path_only():
  uri = y2uri('https://host/folder/item?query=other#section')
  assert uri.endswith('folder/item')
  assert not uri.endswith('section')
  assert not uri.endswith('other')
  uri.path.append('child')
  assert uri.endswith('item/child')
  assert not hasattr(uri, 'startswith')


@pytest.mark.parametrize('form', ['string', 'instance', 'mapping', 'object', 'typed_mapping', 'typed_object'])
def test_uri_constructor_accepts_y2eid_style_inputs(form):
  from types import SimpleNamespace
  text = 'm365://tenant/users/alex?tag=a&tag=b#section'
  original = y2uri(text)
  inputs = {'string': text, 'instance': original, 'mapping': {'uri': text},
    'object': SimpleNamespace(uri=text), 'typed_mapping': {'uri': original},
    'typed_object': SimpleNamespace(uri=original)}
  uri = y2uri(inputs[form])
  assert uri
  assert uri == text
  assert uri.scheme == 'm365'
  assert isinstance(uri.path, y2path)
  assert uri.params == {'tag': ['a', 'b']}
  assert uri.fragment == 'section'
  uri.path.append('child')
  uri.params['tag'].append('c')
  assert original == text


@pytest.mark.parametrize('value', [None, '', {}, 12, [], {'other': 'file:///path'},
  {'uri': None}, {'uri': 12}, {'uri': ''}])
def test_uri_constructor_rejects_empty_and_unsupported_inputs(value):
  uri = y2uri.__new__(y2uri)
  assert not uri
  with pytest.raises(ValueError):
    uri.__init__(value)
  assert not uri


def test_uri_constructor_accepts_location_and_dataobject():
  location = Location({'uid': 'test', 'canonical': 'file:///data'})
  obj = DataObject('file:///data/item', {}, 'item')
  assert y2uri(location) == location.uri
  assert y2uri(obj) == obj.uri


def test_uri_constructor_scheme_matches_eid_namespace_precedence():
  assert y2uri('host/path', 'https') == 'https://host/path'
  assert y2uri(y2path('host/path'), scheme='https') == 'https://host/path'
  assert y2uri('file:///data', scheme='https') == 'file:///data'
  assert y2uri({'uri': 'host/path'}, scheme='https') == 'https://host/path'
  assert y2uri('host/path') == 'null://host/path'
  assert y2uri.default_scheme == 'null'

  class FileURI(y2uri):
    default_scheme = 'file'

  assert FileURI('host/path') == 'file://host/path'
