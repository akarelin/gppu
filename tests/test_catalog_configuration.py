"""Location configuration is usable without filesystems, indexes or provider APIs."""
from copy import deepcopy

import pytest

from gppu import Env, Location, FileLocation
from gppu.fs import GppuCatalog, GppuFileSystem


CONFIG = {
  'connections': {
    'templates': {'connection': {'uri': '{{ scheme ~ "://" ~ authority }}'}},
    'm365-karelin-graph': {'template': 'connection', 'provider': 'm365', 'scheme': 'm365', 'authority': 'karelin'},
    'lake': {'template': 'connection', 'provider': 'file', 'scheme': 'lake', 'authority': ''},
  },
  'location_templates': {
    'location': {},
    'connected': {
      'refs': {'connection': 'connections'},
      'canonical': '{{ connections[connection].uri ~ ("/" if path and not connections[connection].uri.endswith("://") else "") ~ path }}',
    },
  },
  'locations': [
    {'uid': 'm365', 'name': 'M365', 'canonical': 'm365://', 'path': '', 'locations': [
      {'uid': 'm365-karelin-graph', 'name': 'Karelin', 'path': '', 'connection': 'm365-karelin-graph', 'locations': [
        {'uid': 'm365-karelin-graph/alex/contacts', 'name': 'Contacts', 'path': 'alex/contacts'},
      ]},
    ]},
    {'uid': 'lake', 'name': 'Lake', 'path': '', 'connection': 'lake', 'access': '/mnt/S1/Lake/text'},
  ],
}


@pytest.fixture(autouse=True)
def refuse_filesystem(monkeypatch):
  def opened(*args, **kwargs):
    pytest.fail('configuration lookup must not construct a filesystem or index')
  monkeypatch.setattr(GppuFileSystem, '__init__', opened)


def test_native_env_catalog_preserves_input_and_resolves_nested_templates():
  before = deepcopy(CONFIG)
  Env.from_dict(CONFIG)
  catalog = GppuCatalog(location_types={'m365': Location, 'lake': Location})
  assert CONFIG == before
  assert Env.glob_dict('') == before
  assert catalog.ls_sync(detail=False) == ['m365', 'lake']
  assert catalog.ls_sync('m365', detail=False, recurse=True) == [
    'm365-karelin-graph', 'm365-karelin-graph/alex/contacts']
  location = catalog.location('m365-karelin-graph/alex/contacts')
  contact = catalog.info_sync(location.uid)['gppu']
  assert location.parent.uid == 'm365-karelin-graph'
  assert str(location.uri) == 'm365://karelin/alex/contacts'
  assert contact['parent'] == 'm365-karelin-graph'
  assert contact['connection'] == 'm365-karelin-graph'
  assert contact['path'] == 'alex/contacts'
  assert contact['canonical'] == 'm365://karelin/alex/contacts'
  assert catalog.connections[contact['connection']]['provider'] == 'm365'
  assert str(catalog.location('lake').uri_of('Contacts/person.json')) == 'lake://Contacts/person.json'
  assert catalog.info_sync(contact['uid'])['gppu'] == contact
  assert catalog.ls_sync('lake') == []
  contact['name'] = 'Changed outside catalog'
  assert catalog.info_sync(contact['uid'])['gppu']['name'] == 'Contacts'


def test_plain_database_records_use_the_same_catalog_without_templates(tmp_path):
  catalog = GppuCatalog({
    'connections': {'file': {'provider': 'file'}},
    'locations': {
      'local-contacts': {'id': 123, 'path': '', 'connection': 'file', 'canonical': tmp_path.as_uri()},
    },
  })
  assert catalog.info_sync('local-contacts')['gppu']['id'] == 123
  assert catalog.location('local-contacts').container('Contacts').root == (tmp_path / 'Contacts').as_posix()
  assert catalog.ls_sync(detail=False, recurse=True) == ['local-contacts']


@pytest.mark.parametrize('relative', ['../elsewhere', 'Contacts/../../elsewhere', '/etc/passwd', 'smb://s1/other'])
def test_local_path_cannot_escape_location(relative, tmp_path):
  with pytest.raises(ValueError):
    FileLocation({'uid': 'local', 'canonical': tmp_path.as_uri()}).container(relative)


def test_drive_root_stays_absolute():
  location = FileLocation({'uid': 'drive', 'canonical': 'file:///D:/'})
  assert str(location.uri) == 'file:///D:/'
  assert str(location.uri_of('Contacts/person.json')) == 'file:///D:/Contacts/person.json/'


def test_missing_connection_and_parent_are_errors():
  config = deepcopy(CONFIG)
  config['locations'][1]['connection'] = 'missing'
  with pytest.raises(KeyError, match='unknown connection'):
    GppuCatalog(config, location_types={'m365': Location, 'lake': Location})
  config = deepcopy(CONFIG)
  config['locations'][1]['parent'] = 'missing'
  with pytest.raises(KeyError, match='unknown parent'):
    GppuCatalog(config, location_types={'m365': Location, 'lake': Location})


def test_duplicate_and_cyclic_locations_are_errors():
  config = deepcopy(CONFIG)
  config['locations'].append(deepcopy(config['locations'][1]))
  with pytest.raises(ValueError, match='duplicate Location'):
    GppuCatalog(config, location_types={'m365': Location, 'lake': Location})
  config = deepcopy(CONFIG)
  config['locations'][1]['parent'] = 'lake'
  with pytest.raises(ValueError, match='cycle'):
    GppuCatalog(config, location_types={'m365': Location, 'lake': Location})


def test_refresh_is_not_an_implicit_indexing_request():
  catalog = GppuCatalog(CONFIG, location_types={'m365': Location, 'lake': Location})
  with pytest.raises(ValueError, match='reload configuration explicitly'):
    catalog.ls_sync(refresh=True)
  with pytest.raises(ValueError, match='reload configuration explicitly'):
    catalog.info_sync('lake', refresh=True)


def test_nested_paths_are_not_appended_twice():
  config = deepcopy(CONFIG)
  config['locations'][0]['locations'][0]['path'] = 'alex'
  catalog = GppuCatalog(config, location_types={'m365': Location, 'lake': Location})
  assert catalog.info_sync('m365-karelin-graph/alex/contacts')['gppu']['path'] == 'alex/contacts'
