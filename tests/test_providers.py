"""Catalog binds Location implementations; Locations select Containers."""
import pytest

from gppu import FileLocation, Location, y2uri
from gppu.handlers import GppuCatalog


def test_runtime_location_registration_and_child_binding():
  class Graph(Location):
    def container(self, path=''):
      return self.address(path)

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
  assert root.address() == 'plaud://'
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
    assert obj.uri == location.address('item.txt')
    with obj.content as stream:
      assert stream.read() == name.encode()


@pytest.mark.parametrize('path', ['D:/other', '../other', '/etc/passwd', 'smb://server/share'])
def test_container_rejects_nonlocal_object_paths(tmp_path, path):
  container = FileLocation({'uid': 'local', 'canonical': tmp_path.as_uri()}).container()
  with pytest.raises(ValueError):
    container.read(path)
