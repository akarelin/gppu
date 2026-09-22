"""Runtime Provider registration and reversible URI dispatch. No persistent schema registry."""
from dataclasses import dataclass
from importlib import import_module
import re
from string import Formatter
from urllib.parse import quote, unquote


@dataclass(frozen=True)
class ProviderObject:
  uri: str
  content: dict | bytes
  identity: str | None
  kind: str = 'object'
  name: str = ''
  parent: 'ProviderObject | None' = None


@dataclass(frozen=True)
class ProviderCall:
  provider: str
  method: str
  arguments: dict
  uri: str


class Providers:
  """Loaded Provider objects own schemas; Connections and Locations remain caller data."""

  def __init__(self):
    self.providers = {}
    self._schemas = []

  def load(self, module: str):
    """A runtime module registers its Providers through its register(registry) function."""
    import_module(module).register(self)
    return self

  def register(self, provider):
    if provider.uid in self.providers:
      raise ValueError(f'Provider already registered: {provider.uid}')
    declared = []
    for method, template in provider.schemas.items():
      if not callable(getattr(provider, method)):
        raise TypeError(f'{provider.uid}.{method} is not callable')
      fields, pattern = [], ''
      for literal, name, spec, conversion in Formatter().parse(template):
        if spec or conversion:
          raise ValueError('URI schema fields do not use format specifications')
        if name is None:
          pattern += re.escape(literal)
          continue
        if name in fields or not name.isidentifier():
          raise ValueError('URI schema fields must have unique Python names')
        fields.append(name)
        if name == 'path':
          if not literal.endswith('/') or not template.endswith('{path}'):
            raise ValueError('path must be the final, slash-separated URI schema field')
          pattern += re.escape(literal[:-1]) + r'(?:/(?P<path>[^?#]*))?'
        else:
          pattern += re.escape(literal) + f'(?P<{name}>[^/?#]+)'
      declared.append((provider.uid, method, template, tuple(fields), re.compile(pattern)))
    self.providers[provider.uid] = provider
    self._schemas.extend(declared)

  @property
  def schemas(self):
    return [{'provider': provider, 'method': method, 'uri': uri}
            for provider, method, uri, _, _ in self._schemas]

  def uri(self, provider: str, method: str, **arguments) -> str:
    declared = [row for row in self._schemas if row[:2] == (provider, method)]
    if not declared:
      raise KeyError(f'no registered Provider method: {provider}.{method}')
    _, _, template, fields, _ = declared[0]
    if set(arguments) != set(fields):
      raise ValueError(f'{provider}.{method} requires {fields}')
    encoded = {}
    for key, value in arguments.items():
      if key == 'path':
        if not isinstance(value, tuple):
          raise TypeError('path is a tuple of URI segments')
        parts = value
      else:
        parts = (value,)
      if any(not isinstance(part, str) or not part or part in ('.', '..') for part in parts):
        raise ValueError('URI segments must be nonempty names, never dot traversal')
      encoded[key] = '/'.join(quote(part, safe=':@') for part in parts)
    address = template.format(**encoded)
    return address[:-1] if 'path' in arguments and not arguments['path'] and not template.endswith(':///{path}') else address

  def resolve(self, uri: str, provider: str | None = None) -> ProviderCall:
    matches = []
    for owner, method, _, fields, pattern in self._schemas:
      if provider is not None and owner != provider:
        continue
      matched = pattern.fullmatch(uri)
      if matched is None:
        continue
      arguments = {}
      for name in fields:
        raw = matched[name]
        arguments[name] = tuple(unquote(part) for part in raw.split('/')) if name == 'path' and raw else () if name == 'path' else unquote(raw)
      canonical = self.uri(owner, method, **arguments)
      matches.append(ProviderCall(owner, method, arguments, canonical))
    if not matches:
      raise ValueError(f'no loaded Provider schema accepts {uri}')
    if len(matches) != 1:
      raise ValueError(f'ambiguous Provider URI: {uri}')
    return matches[0]

  def open(self, uri: str, connections, provider: str | None = None, connection: str | None = None):
    call = self.resolve(uri, provider)
    arguments = dict(call.arguments)
    uid = arguments.pop('connection') if 'connection' in arguments else connection
    if connection is not None and uid != connection:
      raise ValueError('URI Connection differs from the configured Location Connection')
    connection = connections[uid] if uid is not None else None
    return getattr(self.providers[call.provider], call.method)(connection=connection, **arguments)
