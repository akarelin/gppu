"""Catalog gives each Location its Provider; Locations select Containers."""
import pytest

from gppu import Container, DataObject, FileSystem, Location, Provider, y2uri
from gppu.fs import GppuCatalog


@pytest.mark.parametrize('uid', ['', None, 123])
def test_location_requires_uid_in_configuration_and_enumeration(uid):
  with pytest.raises(ValueError, match='nonempty uid'):
    Location({'uid': uid, 'canonical': 'file:///'})


def test_catalog_uses_location_uid_separately_from_uri():
  uid = 'm365-karelin-graph/users/alex/contacts'
  catalog = GppuCatalog({'connections': {}, 'locations': {
    uid: {'path': 'users/alex/contacts', 'canonical': 'm365://karelin/users/alex/contacts'},
  }}, location_types={'m365': Provider})
  location = catalog.location(uid)
  assert location.uid == uid
  assert catalog.location(uid) is location
  assert location.data['path'] == 'users/alex/contacts'
  assert catalog.ls_sync(detail=False) == [uid]
  with pytest.raises(KeyError):
    catalog.location(str(location.uri))


def test_file_provider_is_available_from_env_without_registration(tmp_path):
  from gppu import Env

  (tmp_path / 'item.txt').write_text('configured file')
  Env.from_dict({'connections': {'disk': {'provider': 'file'}}, 'locations': {
    'files': {'canonical': tmp_path.as_uri(), 'connection': 'disk'},
  }})
  catalog = GppuCatalog()
  assert catalog.schemas == [{'scheme': 'file://', 'implementation': 'FileSystem'}]
  container = catalog.location('files').container()
  with container.read('item.txt').content as stream:
    assert stream.read() == b'configured file'


def test_configured_provider_loads_without_application_registration(monkeypatch):
  import sys
  from types import ModuleType
  from gppu import Env

  class External(Provider):
    scheme = 'external'

  module = ModuleType('test_external_provider')
  module.External = External
  monkeypatch.setitem(sys.modules, module.__name__, module)
  Env.from_dict({'connections': {
    'remote': {'provider': 'test_external_provider.External'},
  }, 'locations': {'remote': {'canonical': 'external://tenant', 'connection': 'remote'},
                   'other': {'canonical': 'external://tenant/other', 'connection': 'remote'}}})
  catalog = GppuCatalog()
  location = catalog.location('remote')
  assert isinstance(location.provider, External)
  assert catalog.location('other').provider is location.provider
  assert location.uri == 'external://tenant'
  assert location.provider.connection['provider'] == 'test_external_provider.External'
  assert catalog.schemas == [
    {'scheme': 'file://', 'implementation': 'FileSystem'},
    {'scheme': 'external://', 'implementation': 'External'},
  ]
  assert GppuCatalog({'connections': {}, 'locations': {}}).schemas == [
    {'scheme': 'file://', 'implementation': 'FileSystem'}]


def test_configured_provider_conflict_is_an_error(monkeypatch):
  import sys
  from types import ModuleType

  class OtherFileSystem(Provider):
    scheme = 'file'

  module = ModuleType('test_conflicting_provider')
  module.OtherFileSystem = OtherFileSystem
  monkeypatch.setitem(sys.modules, module.__name__, module)
  with pytest.raises(ValueError, match='already registered'):
    GppuCatalog({'connections': {
      'disk': {'provider': 'test_conflicting_provider.OtherFileSystem'},
    }, 'locations': {}})


def test_runtime_location_registration_and_child_binding():
  class Graph(Provider):
    scheme = 'm365'

  config = {'connections': {'graph': {'provider': 'm365'}}, 'locations': [
    {'uid': 'graph', 'canonical': 'm365://tenant', 'connection': 'graph', 'locations': [
      {'uid': 'contacts', 'canonical': 'm365://tenant/alex/contacts'},
    ]},
  ]}
  catalog = GppuCatalog(config, location_types={'m365': Graph})
  root = catalog.location('graph')
  contacts = catalog.location('contacts')
  assert isinstance(root.provider, Graph)
  assert root.ls() == [contacts]
  assert contacts.parent is root
  assert contacts.container('folder with space/record%id').uri == 'm365://tenant/alex/contacts/folder%20with%20space/record%25id'
  assert list(root.walk()) == [(root, [contacts]), (contacts, [])]


def test_fixed_root_does_not_require_uri_subdivisions():
  catalog = GppuCatalog({'connections': {}, 'locations': {
    'plaud': {'canonical': 'plaud://'},
  }}, location_types={'plaud': Provider})
  root = catalog.location('plaud')
  assert isinstance(root.uri, y2uri)
  assert root.uri_of() == 'plaud://'
  assert root.ls() == []


def test_unknown_location_fails_and_unregistered_scheme_has_no_container():
  catalog = GppuCatalog({'connections': {}, 'locations': {
    'remote': {'canonical': 'unknown://root'},
  }})
  with pytest.raises(KeyError):
    catalog.location('missing')
  assert catalog.location('remote').provider is None
  with pytest.raises(ValueError, match='no Provider'):
    catalog.location('remote').container()


def test_file_locations_select_independent_containers(tmp_path):
  for name in ('one', 'two'):
    folder = tmp_path / name
    folder.mkdir()
    (folder / 'item.txt').write_text(name)
  catalog = GppuCatalog({'connections': {}, 'locations': {
    name: {'canonical': (tmp_path / name).as_uri()} for name in ('one', 'two')
  }})
  for name in ('one', 'two'):
    location = catalog.location(name)
    assert isinstance(location.provider, FileSystem)
    container = location.container()
    assert container.provider.local(container.uri) == tmp_path / name
    assert container.ls(detail=False) == ['item.txt']
    obj = container.read('item.txt')
    assert obj.uri == location.uri_of('item.txt')
    with obj.content as stream:
      assert stream.read() == name.encode()


def test_file_write_uses_explicit_path_and_checks_source_identity(tmp_path):
  container = Location({'uid': 'files', 'canonical': tmp_path.as_uri()}, provider=FileSystem(), templates={
    'date': "{{ '2026-09-22' if 'plaud://' in uri else '' }}",
    'filename': "{{ date.year }}/{{ uri.split('://')[1] }}.json",
    'identity': "{{ it.id if uri.startswith('plaud://') else none }}",
  }).container()
  obj = DataObject(y2uri('plaud://recording'), {'id': 'recording', 'name': 'Before'}, 'recording')
  (tmp_path / 'chosen').mkdir()
  (tmp_path / 'chosen/.merge.yaml').write_text('[upsert]')
  container.write('chosen/recording.json', obj)
  container.write('chosen/recording.json', DataObject(obj.uri, {'id': 'recording', 'name': 'After'}, 'recording'))
  assert container.read('chosen/recording.json').content['name'] == 'After'
  assert not (tmp_path / '2026').exists()
  with pytest.raises(ValueError, match='different object identity'):
    container.write('chosen/recording.json', DataObject(obj.uri, {'id': 'other'}, 'other'))
  assert container.read('chosen/recording.json').content['id'] == 'recording'
  assert isinstance(obj.uri, y2uri)


def test_file_write_without_templates_round_trips_json_and_binary(tmp_path):
  from io import BytesIO
  from gppu import y2path

  container = Container(FileSystem(), tmp_path.as_uri())
  obj = DataObject('file:///source/object', {'value': 'text'}, 'source')
  container.write(y2path('nested/value.json'), obj)
  assert container.read('nested/value.json').content == obj.content
  assert str(obj.uri) == 'file:///source/object'
  for content in (b'\x00\xff', BytesIO(b'\x00\xff')):
    container.write('nested/value.bin', DataObject(obj.uri, content, obj.identity))
  with container.read('nested/value.bin').content as stream:
    assert stream.read() == b'\x00\xff'
  with pytest.raises(FileExistsError, match='rule in its folder'):
    container.write('nested/value.bin', DataObject(obj.uri, b'changed', obj.identity))
  container.delete('nested/value.bin')
  container.write('nested/value.bin', DataObject(obj.uri, b'changed', obj.identity))
  assert (tmp_path / 'nested/value.bin').read_bytes() == b'changed'


@pytest.mark.parametrize('path', ['', '.', '../outside', '/absolute', 'C:/absolute', 'file:///outside', r'folder\file'])
def test_file_write_rejects_invalid_destination_before_writing(tmp_path, path):
  container = Container(FileSystem(), tmp_path.as_uri())
  with pytest.raises(ValueError):
    container.write(path, DataObject('file:///source', b'data', 'source'))
  assert list(tmp_path.iterdir()) == []


def test_container_deletes_by_path_and_escapes_names(tmp_path):
  target = tmp_path / 'space #percent%.json'
  target.write_text('{"value": true}')
  sibling = tmp_path / 'keep.json'
  sibling.write_text('{}')
  Container(FileSystem(), tmp_path.as_uri()).delete('space #percent%.json')
  assert not target.exists()
  assert sibling.read_text() == '{}'


def test_file_provider_deletes_by_uri_and_refuses_traversal(tmp_path):
  root = tmp_path / 'container'
  root.mkdir()
  inside = root / 'gone.json'
  inside.write_text('{}')
  outside = tmp_path / 'keep.json'
  outside.write_text('{}')
  FileSystem().delete(y2uri(inside.as_uri()))
  assert not inside.exists()
  with pytest.raises(ValueError, match='traversal'):
    FileSystem().delete(root.as_uri() + '/%2e%2e/keep.json')
  assert outside.read_text() == '{}'


@pytest.mark.parametrize('suffix', ['?key=value', '#part'])
def test_file_provider_rejects_uri_query_and_fragment(tmp_path, suffix):
  target = tmp_path / 'keep.json'
  target.write_text('{}')
  with pytest.raises(ValueError, match='query or fragment'):
    FileSystem().delete(target.as_uri() + suffix)
  assert target.read_text() == '{}'


def test_read_only_provider_refuses_writes_and_discovers_locations():
  class Tenant(Provider):
    scheme = 'm365'
    def locations(self, uri):
      return [('users', 'Users')] if uri == 'm365://tenant' else []
    def ls(self, uri):
      return [{'name': 'item', 'type': 'file', 'size': None}]
    def read(self, uri):
      return DataObject(uri, {'id': 'native'}, 'native')

  root = Location({'uid': 'tenant', 'canonical': 'm365://tenant'}, provider=Tenant())
  users, = root.ls()
  assert (users.uid, users.uri, users.parent, users.data['name']) == ('tenant/users', 'm365://tenant/users', root, 'Users')
  container = users.container()
  assert container.ls(detail=False) == ['item']
  assert container.read('item').uri == 'm365://tenant/users/item'
  with pytest.raises(PermissionError):
    container.write('item', DataObject('m365://tenant/users/item', {}, 'native'))
  with pytest.raises(PermissionError):
    container.delete('item')
  with pytest.raises(ValueError, match='no Provider'):
    Location({'uid': 'group', 'canonical': 'group://'}).container()


@pytest.mark.parametrize('path', ['D:/other', '../other', '/etc/passwd', 'smb://server/share'])
def test_container_rejects_nonlocal_object_paths(tmp_path, path):
  container = Location({'uid': 'local', 'canonical': tmp_path.as_uri()}, provider=FileSystem()).container()
  with pytest.raises(ValueError):
    container.read(path)



def test_lake_write_leaves_matching_files_and_grows_append_only_ones(tmp_path):
  container = Container(FileSystem(), tmp_path.as_uri())
  held = tmp_path / 'omi/detail.json'
  held.parent.mkdir()
  held.write_text('{\n  "id": "c1",\n  "title": "Walk"\n}\n', encoding='utf-8')
  before = held.stat().st_mtime_ns
  container.write('omi/detail.json', DataObject('omi://c1', {'title': 'Walk', 'id': 'c1'}, 'c1'))
  assert held.stat().st_mtime_ns == before
  with pytest.raises(FileExistsError):
    container.write('omi/detail.json', DataObject('omi://c1', {'id': 'c1', 'title': 'Edited'}, 'c1'))
  assert '"Walk"' in held.read_text(encoding='utf-8')
  container.write('log.jsonl', DataObject('file:///log', b'one\n', 'log'))
  container.write('log.jsonl', DataObject('file:///log', b'one\ntwo\n', 'log'))
  assert (tmp_path / 'log.jsonl').read_bytes() == b'one\ntwo\n'
  for shorter_or_other in (b'one\n', b'two\none\n'):
    with pytest.raises(FileExistsError):
      container.write('log.jsonl', DataObject('file:///log', shorter_or_other, 'log'))
  assert (tmp_path / 'log.jsonl').read_bytes() == b'one\ntwo\n'
  assert sorted(path.name for path in tmp_path.rglob('*')) == ['detail.json', 'log.jsonl', 'omi']


def test_lake_write_follows_the_nearest_merge_rule_of_its_folder(tmp_path):
  container = Container(FileSystem(), tmp_path.as_uri())
  (tmp_path / 'contacts/people').mkdir(parents=True)
  (tmp_path / 'contacts/.merge.yaml').write_text('- upsert\n- delete\n')
  (tmp_path / 'contacts/people/ann.json').write_text('{"name": "Ann"}')
  container.write('contacts/people/ann.json', DataObject('m365://ann', {'name': 'Ann B'}, 'ann'))
  assert container.read('contacts/people/ann.json').content == {'name': 'Ann B'}
  container.write('contacts/people/bob.json', DataObject('m365://bob', {'name': 'Bob'}, 'bob'))
  container.write('contacts/people/ann.json', DataObject('m365://ann', b'', 'ann', removed=True))
  container.write('contacts/people/gone.json', DataObject('m365://gone', b'', 'gone', removed=True))
  assert sorted(path.name for path in (tmp_path / 'contacts/people').iterdir()) == ['bob.json']
  assert container.rules('contacts/people/bob.json') == {'upsert', 'delete'}
  assert container.rules('elsewhere/x.json') == frozenset()


def test_lake_write_update_replaces_held_files_and_keeps_removed_ones(tmp_path):
  container = Container(FileSystem(), tmp_path.as_uri())
  (tmp_path / 'contacts').mkdir()
  (tmp_path / 'contacts/.merge.yaml').write_text('[update]')
  (tmp_path / 'contacts/ann.json').write_text('{"name": "Ann"}')
  container.write('contacts/ann.json', DataObject('m365://ann', {'name': 'Ann B'}, 'ann'))
  container.write('contacts/bob.json', DataObject('m365://bob', {'name': 'Bob'}, 'bob'))
  container.write('contacts/ann.json', DataObject('m365://ann', b'', 'ann', removed=True))
  assert sorted(path.name for path in (tmp_path / 'contacts').glob('*.json')) == ['ann.json', 'bob.json']
  assert container.read('contacts/ann.json').content == {'name': 'Ann B'}


def test_lake_write_refuses_an_unspecified_merge_rule(tmp_path):
  container = Container(FileSystem(), tmp_path.as_uri())
  (tmp_path / '.merge.yaml').write_text('[deep merge]')
  (tmp_path / 'ann.json').write_text('{"name": "Ann"}')
  with pytest.raises(ValueError, match='not specified'):
    container.write('ann.json', DataObject('m365://ann', {'name': 'Ann B'}, 'ann'))
  assert (tmp_path / 'ann.json').read_text() == '{"name": "Ann"}'
