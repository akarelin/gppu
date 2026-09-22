"""Provider registration is runtime-only; URI dispatch and construction are inverse."""
import pytest

from gppu.providers import Providers


class Graph:
  uid = 'm365-graph'
  schemas = {'root': 'm365://{connection}', 'contacts': 'm365://{connection}/{user}/contacts/{path}',
             'todo': 'm365://{connection}/{user}/todo/{path}'}

  def root(self, connection):
    return connection

  def contacts(self, connection, user, path):
    return connection, user, path

  todo = contacts


def test_runtime_registration_dispatch_and_reverse():
  registry = Providers()
  assert registry.schemas == []
  registry.register(Graph())
  for connection in ('karelin', 'tulaco'):
    for method in ('contacts', 'todo'):
      for path in ((), ('folder with space',), ('folder/encoded', 'record%id')):
        args = {'connection': connection, 'user': 'alex', 'path': path}
        uri = registry.uri('m365-graph', method, **args)
        call = registry.resolve(uri)
        assert (call.provider, call.method, call.arguments, call.uri) == ('m365-graph', method, args, uri)
        assert registry.open(uri, {connection: {'tenant': connection}}) == ({'tenant': connection}, 'alex', path)
  assert registry.resolve('m365://karelin').method == 'root'


def test_fixed_root_does_not_require_uri_subdivisions():
  class Plaud:
    uid = 'plaud'
    schemas = {'root': 'plaud://'}
    def root(self, connection):
      return connection
  registry = Providers()
  registry.register(Plaud())
  assert registry.uri('plaud', 'root') == 'plaud://'
  assert registry.open('plaud://', {'plaud': {'token': 'test'}}, connection='plaud') == {'token': 'test'}
  with pytest.raises(ValueError, match='no loaded Provider'):
    registry.resolve('plaud://invented-folder')


def test_missing_and_ambiguous_routes_fail():
  registry = Providers()
  registry.register(Graph())
  with pytest.raises(ValueError, match='already registered'):
    registry.register(Graph())
  with pytest.raises(ValueError, match='no loaded Provider'):
    registry.resolve('m365://karelin/alex/unknown')
  with pytest.raises(KeyError):
    registry.open('m365://missing', {})
  with pytest.raises(ValueError, match='differs'):
    registry.open('m365://karelin', {}, connection='tulaco')
  with pytest.raises(ValueError, match='dot traversal'):
    registry.resolve('m365://karelin/alex/contacts/%2e%2e')


def test_file_provider_root_and_multiple_location_paths(tmp_path):
  registry = Providers().load('gppu.file_provider')
  for path in (tmp_path, tmp_path / 'one', tmp_path / 'two'):
    uri = path.as_uri()
    call = registry.resolve(uri)
    assert registry.uri(call.provider, call.method, **call.arguments) == uri
    assert registry.open(uri, {}).root.replace('\\', '/') == str(path).replace('\\', '/')
  assert registry.resolve('file:///').uri == 'file:///'
