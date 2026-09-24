"""Catalog binds Location implementations; Locations select Containers."""
import pytest

from gppu import FileLocation, Location, y2uri
from gppu.handlers import GppuCatalog


@pytest.mark.parametrize('uid', ['', None, 123])
def test_location_requires_uid_in_configuration_and_enumeration(uid):
  with pytest.raises(ValueError, match='nonempty uid'):
    Location({'uid': uid, 'canonical': 'file:///'})


def test_catalog_uses_location_uid_separately_from_uri():
  uid = 'm365-karelin-graph/users/alex/contacts'
  catalog = GppuCatalog({'connections': {}, 'locations': {
    uid: {'path': 'users/alex/contacts', 'canonical': 'm365://karelin/users/alex/contacts'},
  }}, location_types={'m365': Location})
  location = catalog.location(uid)
  assert location.uid == uid
  assert catalog.location(uid) is location
  assert location.my('path') == 'users/alex/contacts'
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
  assert catalog.schemas == [{'scheme': 'file://', 'implementation': 'FileLocation'}]
  container = catalog.location('files').container()
  with container.read('item.txt').content as stream:
    assert stream.read() == b'configured file'


def test_configured_provider_loads_without_application_registration(monkeypatch):
  import sys
  from types import ModuleType
  from gppu import Env

  class ExternalLocation(Location):
    scheme = 'external'

  module = ModuleType('test_external_provider')
  module.ExternalLocation = ExternalLocation
  monkeypatch.setitem(sys.modules, module.__name__, module)
  Env.from_dict({'connections': {
    'remote': {'provider': 'test_external_provider.ExternalLocation'},
  }, 'locations': {'remote': {'canonical': 'external://tenant', 'connection': 'remote'}}})
  catalog = GppuCatalog()
  location = catalog.location('remote')
  assert isinstance(location, ExternalLocation)
  assert location.uri == 'external://tenant'
  assert location._connection['provider'] == 'test_external_provider.ExternalLocation'
  assert catalog.schemas == [
    {'scheme': 'file://', 'implementation': 'FileLocation'},
    {'scheme': 'external://', 'implementation': 'ExternalLocation'},
  ]
  assert GppuCatalog({'connections': {}, 'locations': {}}).schemas == [
    {'scheme': 'file://', 'implementation': 'FileLocation'}]


def test_configured_provider_conflict_is_an_error(monkeypatch):
  import sys
  from types import ModuleType

  class OtherFileLocation(Location):
    scheme = 'file'

  module = ModuleType('test_conflicting_provider')
  module.OtherFileLocation = OtherFileLocation
  monkeypatch.setitem(sys.modules, module.__name__, module)
  with pytest.raises(ValueError, match='already registered'):
    GppuCatalog({'connections': {
      'disk': {'provider': 'test_conflicting_provider.OtherFileLocation'},
    }, 'locations': {}})


def test_runtime_location_registration_and_child_binding():
  class Graph(Location):
    def container(self, path=''):
      return self.uri_of(path)

  config = {'connections': {'graph': {'provider': 'm365'}}, 'locations': [
    {'uid': 'graph', 'canonical': 'm365://tenant', 'connection': 'graph', 'locations': [
      {'uid': 'contacts', 'canonical': 'm365://tenant/alex/contacts'},
    ]},
  ]}
  catalog = GppuCatalog(config, location_types={'m365': Graph})
  root = catalog.location('graph')
  contacts = catalog.location('contacts')
  assert isinstance(root, Graph)
  assert root.ls() == [contacts]
  assert contacts.parent is root
  assert contacts.container('folder with space/record%id') == 'm365://tenant/alex/contacts/folder%20with%20space/record%25id'
  assert list(root.walk()) == [(root, [contacts]), (contacts, [])]


def test_fixed_root_does_not_require_uri_subdivisions():
  catalog = GppuCatalog({'connections': {}, 'locations': {
    'plaud': {'canonical': 'plaud://'},
  }}, location_types={'plaud': Location})
  root = catalog.location('plaud')
  assert isinstance(root.uri, y2uri)
  assert root.uri_of() == 'plaud://'
  assert root.ls() == []


def test_unknown_location_and_unregistered_scheme_fail():
  catalog = GppuCatalog({'connections': {}, 'locations': {
    'remote': {'canonical': 'unknown://root'},
  }})
  with pytest.raises(KeyError):
    catalog.location('missing')
  with pytest.raises(KeyError):
    catalog.location('remote')


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
    assert isinstance(location, FileLocation)
    container = location.container()
    assert container.root == (tmp_path / name).as_posix()
    assert container.ls(detail=False) == ['item.txt']
    obj = container.read('item.txt')
    assert obj.uri == location.uri_of('item.txt')
    with obj.content as stream:
      assert stream.read() == name.encode()


def test_file_templates_receive_uri_text_and_keep_typed_objects(tmp_path):
  from gppu import DataObject

  container = FileLocation({'uid': 'files', 'canonical': tmp_path.as_uri()}, templates={
    'date': "{{ '2026-09-22' if 'plaud://' in uri else '' }}",
    'filename': "{{ date.year }}/{{ uri.split('://')[1] }}.json",
    'identity': "{{ it.id if uri.startswith('plaud://') else none }}",
  }).container()
  obj = DataObject(y2uri('plaud://recording'), {'id': 'recording', 'name': 'Before'}, 'recording')
  container.write(obj)
  container.write(DataObject(obj.uri, {'id': 'recording', 'name': 'After'}, 'recording'))
  assert container.read('2026/recording.json').content['name'] == 'After'
  assert isinstance(obj.uri, y2uri)


@pytest.mark.parametrize('path', ['D:/other', '../other', '/etc/passwd', 'smb://server/share'])
def test_container_rejects_nonlocal_object_paths(tmp_path, path):
  container = FileLocation({'uid': 'local', 'canonical': tmp_path.as_uri()}).container()
  with pytest.raises(ValueError):
    container.read(path)
