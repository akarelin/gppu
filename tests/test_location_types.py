import json

import pytest

from gppu import y2path, y2uri
from gppu.fs import Container, DataObject, FileSystem, Location


@pytest.mark.parametrize('value', [
  'file:///', 'file:///D:/folder/name%20with%20space', 'file://server/share/',
  'm365://tenant/users/alex/contacts/id%2Fpart', 'plaud://',
])
def test_uri_round_trip(value):
  uri = y2uri(value)
  assert isinstance(uri.path, y2path)
  assert y2uri(uri) == value
  assert json.loads(json.dumps({'uri': uri.to_json()})) == {'uri': value}


@pytest.mark.parametrize('root, expected', [
  ('file:///', 'file:///folder/item'),
  ('file:///D:/', 'file:///D:/folder/item/'),
  ('file://server/share/', 'file://server/share/folder/item/'),
  ('https://host/a/b/', 'https://host/a/b/folder/item/'),
  ('plaud://', 'plaud://folder/item'),
])
def test_uri_joins_preserve_leading_and_trailing_slashes(root, expected):
  original = y2uri(root)
  assert str(original / 'folder' / 'item') == expected
  assert str(original / y2path('folder/item')) == expected
  assert str(original) == root


def test_location_and_file_container_use_types(tmp_path):
  (tmp_path / 'folder').mkdir()
  (tmp_path / 'folder' / 'item.json').write_text('{"value": true}')
  location = Location({'uid': 'test', 'canonical': tmp_path.as_uri()}, provider=FileSystem())
  assert isinstance(location.uri, y2uri)
  assert isinstance(Location.relative('folder'), y2path)
  assert location.uri_of(y2path('name #%.json')).path.tail == 'name%20%23%25.json'
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



def test_dataobject_constructs_uri_type():
  obj = DataObject('file:///data/item', {}, 'item')
  assert isinstance(obj.uri, y2uri)
  assert isinstance(obj.uri / y2path('child'), y2uri)


def test_file_write_renders_source_uri_as_text_in_template(tmp_path):
  container = Container(FileSystem(), tmp_path.as_uri(), templates={'filename': '{{ uri.rsplit("/", 1)[1] }}.json'})
  obj = DataObject(y2uri('m365://tenant') / y2path('item'), {'value': True}, 'item')
  container.write(y2path('item.json'), obj)
  assert container.read(y2path('item.json')).content == obj.content
  assert container.read(obj).uri == obj.uri
  container.delete('item.json')
  assert container.ls() == []

@pytest.mark.parametrize('suffix', ['folder/item', y2path('folder/item')])
def test_uri_path_join_keeps_original_and_metadata(suffix):
  original = y2uri('m365://tenant?tag=a&tag=b#section')
  joined = original / suffix
  assert isinstance(joined, y2uri)
  assert isinstance(joined.path, y2path)
  assert joined is not original and joined.path is not original.path
  assert str(joined) == 'm365://tenant/folder/item?tag=a&tag=b#section'
  joined.path.iadd('child')
  joined.query = 'other=value'
  joined.fragment = 'other'
  assert str(original) == 'm365://tenant?tag=a&tag=b#section'
  assert str(original / 'folder' / 'item') == 'm365://tenant/folder/item?tag=a&tag=b#section'
  assert original / '' == original


def test_path_join_returns_independent_path():
  original = y2path('folder')
  for suffix in ('child/item', y2path('child/item')):
    joined = original / suffix
    assert isinstance(joined, y2path)
    assert str(joined) == 'folder/child/item'
    joined.iadd('more')
    assert str(original) == 'folder'


def test_uri_keeps_slash_markers_without_interpreting_path_components():
  uri = y2uri('custom:///C:/folder/?q=value#section')
  assert uri.path == y2path(['C:', 'folder'])
  assert not hasattr(uri, 'authority')
  assert str(uri) == 'custom:///C:/folder/?q=value#section'
  assert str(uri / 'child') == 'custom:///C:/folder/child/?q=value#section'
  assert str(uri / 'child/') == 'custom:///C:/folder/child/?q=value#section'
  assert str(uri) == 'custom:///C:/folder/?q=value#section'
  assert y2path('/a//b/', ['c', '', 'd']).data == ['a', 'b', 'c', 'd']


def test_uri_format_does_not_control_path_joining():
  uri = y2uri('custom:///folder?q=value#section')
  uri._last_segment_empty = True
  joined = uri / 'child'
  assert joined._path_absolute is True
  assert joined._last_segment_empty is True
  assert joined.path.data == ['folder', 'child']
  assert str(joined) == 'custom:///folder/child/?q=value#section'
  assert joined.scheme == 'custom'
  assert joined.query == 'q=value'
  assert joined.fragment == 'section'
  assert str(uri) == 'custom:///folder/?q=value#section'


def test_uri_mutation_updates_representation_and_equality():
  uri = y2uri('file://host/folder')
  uri.scheme = 'xxx'
  uri.path.iadd('item')
  assert str(uri) == 'xxx://host/folder/item'
  assert uri == 'xxx://host/folder/item'
  assert 'xxx://host/folder/item' == uri
  assert {uri: 'found'}[str(uri)] == 'found'
  copied = y2uri(uri)
  copied.path.iadd('child')
  assert str(uri) == 'xxx://host/folder/item'


@pytest.mark.parametrize('text', [
  'https://host/path?q=hello+world&empty=&tag=a&tag=b#section',
  'https://host/video?t=1,2#t=10,20&xywh=percent:10,20,30,40',
  'https://host/page#section:~:text=before-,hello%2C%20world,-after&text=other',
  'https://host/page#chapter%201',
])
def test_uri_query_and_fragment_are_raw_strings(text):
  uri = y2uri(text)
  assert str(uri) == text
  assert uri.fragment == text.partition('#')[2]
  assert uri.query == text.partition('#')[0].partition('?')[2]
  uri.query = 'new=raw%20value'
  uri.fragment = 'next%20section'
  assert str(uri).endswith('?new=raw%20value#next%20section')
  assert (uri / 'child').query == uri.query
  assert (uri / 'child').fragment == uri.fragment
  uri.query = ''
  uri.fragment = ''
  assert str(uri) == 'https://' + str(uri.path)


def test_uri_constructor_native_inputs_and_scheme_conflict():
  text = 'm365://tenant/users/alex?tag=a&tag=b#section'
  original = y2uri(text)
  for value in (text, original, {'uri': text}):
    uri = y2uri(value)
    assert str(uri) == text
    uri.path.iadd('child')
    assert str(original) == text
  assert y2uri('host/path') == 'null://host/path'
  assert y2uri('host/path', 'https') == 'https://host/path'
  assert y2uri(y2path('host/path'), scheme='https') == 'https://host/path'
  assert y2uri({'uri': 'host/path'}, scheme='https') == 'https://host/path'
  with pytest.raises(ValueError, match='Two schemas'):
    y2uri('file://host/path', scheme='https')
