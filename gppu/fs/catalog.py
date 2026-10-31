r"""The catalog: where every location is and what is in each.

  GppuCatalog             the locations as Location objects, each with the Provider of its connection
  catalog(records)        the catalog of Linked Data's location records, as its user read them from /fs/locations
  Catalog(records, ld)    what is in the locations: the catalog's database, Linked Data's fs files and instances, its API /lake/catalog, and
  CatalogFileSystem(url)  what is in the locations through that API as an fsspec filesystem, read-only"""
import asyncio
import functools
import importlib
import json
import os
import posixpath
import re
import socket
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID

import yaml
from fsspec.asyn import AsyncFileSystem
from fsspec.core import split_protocol
from fsspec.spec import AbstractFileSystem

from ..app import glob
from ..gppu import TemplateSet, TimeSpan, full_path, uuid_create, y2path
from .uri import y2uri
from . import FileSystem, Location, Provider, _address, _below
from .gppufs import GppuFileSystem


# region locations

class GppuCatalog(AsyncFileSystem):
  """A catalog of Locations keyed by uid.

  ``GppuCatalog(rows)`` resolves the connections and nested Locations its user
  gives it: the rows are loaded by whoever uses the catalog, from its
  configuration or from Linked Data. ``ls(recurse=True)`` walks that tree.
  ``location(uid)`` returns the Location whose ``ls`` and ``walk`` enumerate
  its child Locations.

  FileSystem is built in. A connection's ``provider`` can name an external
  Provider by its Python module and class; configuration loading imports it and
  registers its declared scheme. ``schemas`` reports the loaded schemes. Each
  connection gets one Provider instance, shared by every Location it reaches.

  The explicit folder argument retains the existing exported-host catalog:

  ``catalog`` is an absolute folder with one subfolder per host or server, named
  as the Locations table names it, holding that host's ``locations.yaml``: one
  row per Location as the table has it, plus ``root_path`` and ``index``, where
  that Location keeps its gppufs index. The host's folder is chosen by the
  machine name unless ``host`` says otherwise. The JSON files beside the host
  folders are the global catalog, one per service, the file name being the
  service: ``sharepoint.yaml``, ``synology-drive.yaml``, ``git.yaml`` and
  so on. Each holds the canonical ``locations`` of that service, nested, a
  location carrying its children in its own ``locations``, servers at the top.
  The host folder's ``replicas.yaml`` says, per service, where this host holds
  a copy of a location, named by its path of names in that tree, and when that
  was last checked. A folder that is a replica carries a ``source`` block: the
  service, the location's path of names, its server, what the catalog says of
  it, and ``checked_at``. The catalog root lists the Locations without touching
  them. Every address at or below a Location is listed by the catalog's one
  :class:`GppuFileSystem`; the deepest Location whose root contains the address
  owns it. A Location root's parent is its parent Location when the catalog
  names one, otherwise the catalog root, so a browser walks the Locations tree.
  """

  protocol = 'gppu-catalog'
  cachable = False

  def __init__(self, catalog: str | Path | Mapping, host: str | None = None,
               location_types: Mapping | None = None, templates: Mapping[str, str] | None = None) -> None:
    self.location_types = {'file': FileSystem}
    if location_types is not None:
      self.location_types.update(location_types)
    self.templates = templates
    self._providers: dict[str | None, Provider] = {}
    self._configuration = isinstance(catalog, Mapping)
    if self._configuration:
      super().__init__()
      self.host = host or socket.gethostname().split('.')[0].lower()
      self.root = 'gppu-catalog://'
      self._lock = RLock()
      self._config = deepcopy(dict(catalog))
      self._bound_locations = {}
      self._here: dict[str, str] | None = None   # each location's folder on this host, found once (`reached`)
      self._load_configuration()
      return
    if not Path(catalog).is_absolute():
      raise ValueError(f'{catalog}: the catalog is an absolute folder path')
    super().__init__()
    self.catalog = Path(catalog)
    self.host = host or socket.gethostname()
    folders = {folder.name.casefold(): folder for folder in self.catalog.iterdir() if folder.is_dir()}
    if self.host.casefold() not in folders:
      raise ValueError(f'{catalog}: no folder for host {self.host}')
    self.folder = folders[self.host.casefold()]
    self.sources: dict[str, dict] = {file.stem: yaml.safe_load(file.read_text(encoding='utf-8'))
      for file in sorted(self.catalog.glob('*.yaml'))}
    canonical: dict[tuple[str, str], dict] = {}
    def walk(service: str, entries: list[dict], above: tuple[str, ...]) -> None:
      for location in entries:  # a location carries its children in its own ``locations``; the top level is a server
        names = (*above, location['name'])
        canonical[service, '/'.join(names)] = {'service': service, 'location': '/'.join(names),
          **({'server': names[0]} if len(names) > 1 else {}),
          **{field: value for field, value in location.items() if field != 'locations'}}
        walk(service, location.get('locations', []), names)
    for service, source in self.sources.items():
      walk(service, source['locations'], ())
    replicas = self.folder / 'replicas.yaml'
    self._replicas: dict[str, dict] = {}
    listed = yaml.safe_load(replicas.read_text(encoding='utf-8')) or {} if replicas.is_file() else {}
    for service, entries in listed.items():
      for replica in entries:
        location = canonical.get((service, replica['location']))
        if location is None:
          raise ValueError(f"{replicas}: {replica['path']} is a replica of {service} {replica['location']}, which {service}.yaml does not list")
        self._replicas[os.path.normcase(os.path.normpath(replica['path']))] = {**location, 'checked_at': replica['checked_at']}
    self.root = f'gppu-catalog://{self.catalog.as_posix()}'
    self._lock = RLock()
    self.files = GppuFileSystem()   # what is in the locations, as gppufs lists it
    self._roots: dict[str, str] = {}   # a location's root_path -> its folder as gppufs names it
    self._split: set[str] = set()   # the locations given their own index by this instance
    self._load()

  def _load_configuration(self) -> None:
    """Resolve configured Locations without opening any provider or index.

    The input is the tree the catalog's user loaded, from its configuration or
    from a database. Nested paths are provider-relative, never appended to
    their parent's path. Loading does not mutate the supplied mapping.
    """
    config = self._config
    definitions = config['connections']
    connection_templates = definitions['templates'] if 'templates' in definitions else {}
    connection_rules = TemplateSet(templates=connection_templates, context=config)
    self.connections = {
      uid: connection_rules.resolve({'uid': uid, **row})
      for uid, row in definitions.items()
      if uid not in ('templates', 'macros', 'generators') and not uid.endswith('_templates')
    }
    for connection in self.connections.values():
      if 'provider' not in connection:
        continue
      provider = connection['provider']
      if provider in self.location_types:
        continue
      module, _, name = provider.rpartition('.')
      if not module:
        raise ValueError(f'{provider}: unknown configured provider')
      kind = getattr(importlib.import_module(module), name)
      if not isinstance(kind, type) or not issubclass(kind, Provider):
        raise TypeError(f'{provider}: provider must implement Provider')
      if kind.scheme in self.location_types and self.location_types[kind.scheme] is not kind:
        raise ValueError(f'{kind.scheme}: provider already registered')
      self.location_types[kind.scheme] = kind
    tree = config['locations']
    if isinstance(tree, Mapping):
      templates = tree['templates'] if 'templates' in tree else {}
      entries = [{'uid': uid, **row} for uid, row in tree.items()
                 if uid not in ('templates', 'macros', 'generators') and not uid.endswith('_templates')]
    elif isinstance(tree, list):
      templates = config['location_templates'] if 'location_templates' in config else {}
      entries = tree
    else:
      raise TypeError('locations must be a list or a mapping keyed by uid')
    context = {**config, 'connections': self.connections, 'host': self.host}
    rules = TemplateSet(templates=templates, context=context)
    self.locations = {}
    self._parents = {}

    def add(items, parent=None, connection=None):
      if not isinstance(items, list):
        raise TypeError('nested locations must be a list')
      for item in items:
        row = dict(item)
        uid = row['uid']
        if not isinstance(uid, str) or not uid:
          raise ValueError('every Location requires a nonempty uid')
        if uid in self.locations:
          raise ValueError(f'duplicate Location uid: {uid}')
        children = row.pop('locations') if 'locations' in row else []
        owner = row['parent'] if 'parent' in row else parent
        if parent is not None and owner != parent:
          raise ValueError(f'{uid}: parent conflicts with its nested Location')
        serving = row['connection'] if 'connection' in row else connection
        if serving is not None:
          if serving not in self.connections:
            raise KeyError(f'{uid}: unknown connection {serving}')
          row['connection'] = serving
        if templates and 'template' not in row:
          row['template'] = 'connected' if serving is not None else 'location'
        row['parent'] = owner
        resolved = rules.resolve(row)
        resolved['parent'] = owner
        self.locations[uid] = resolved
        self._parents[uid] = owner
        add(children, uid, serving)

    add(entries)
    for uid, parent in self._parents.items():
      visited = {uid}
      while parent is not None:
        if parent not in self.locations:
          raise KeyError(f'{uid}: unknown parent Location {parent}')
        if parent in visited:
          raise ValueError(f'{uid}: Location hierarchy contains a cycle')
        visited.add(parent)
        parent = self._parents[parent]

  def _provider(self, scheme: str, connection: str | None) -> Provider | None:
    """The one Provider instance for a connection, or for a scheme reached without one."""
    if scheme not in self.location_types:
      return None
    key = connection if connection is not None else scheme + '://'
    if key not in self._providers:
      self._providers[key] = self.location_types[scheme](self.connections[connection] if connection is not None else None)
    return self._providers[key]

  def location(self, uid: str) -> Location:
    """Return the Location with this UID, with the Provider of its connection, and its folder on this host when it has one
    (`reached`), which its Container reads.

    Args:
      uid (str): Location UID from the configured tree.

    Returns:
      Location: The configured Location. Repeated calls with the same UID return
        the same instance. A missing UID raises KeyError.
    """
    if not self._configuration:
      raise TypeError('Location operations require a configured catalog')
    with self._lock:
      if uid not in self._bound_locations:
        row = self.locations[uid]
        parent = self._parents[uid]
        if self._here is None:
          self._here = {found['location']: folder for folder, found in reached(self).items()}
        folder = self._here.get(uid)
        self._bound_locations[uid] = Location(row,
          provider=self._provider(urlsplit(row['canonical']).scheme, row.get('connection')),
          parent=self.location(parent) if parent is not None else None,
          children=lambda: (self.location(child) for child, owner in self._parents.items() if owner == uid),
          templates=self.templates,
          here=None if folder is None else (self._provider('file', None), y2uri(Path(folder).as_uri())))
      return self._bound_locations[uid]

  def location_of(self, uri: y2uri | str) -> tuple[Location, y2path]:
    """The nearest configured Location at or above uri, walking up one segment at a time, and the path below it."""
    by_uri = {self._bare(row['canonical']): uid for uid, row in self.locations.items()}
    at, below = self._bare(uri), []
    while at not in by_uri:
      scheme, _, rest = at.partition('://')
      if not rest:
        raise KeyError(f'{uri}: no configured Location holds this uri')
      head, _, name = rest.rpartition('/')
      at = f'{scheme}://{head}'
      below.insert(0, name)
    location = self.location(by_uri[at])
    if isinstance(location.provider, FileSystem) and not urlsplit(at).path and below:
      # A host has no folder of its own: the drive below it is the root of what is listed.
      location = Location({'uid': location.uid, 'canonical': f'{at}/{below.pop(0)}'}, provider=location.provider,
                          parent=location, templates=location.templates)
    return location, y2path(unquote('/'.join(below)))

  @staticmethod
  def _bare(uri: y2uri | str) -> str:
    """uri without a trailing slash; a scheme's own root keeps its '://'."""
    scheme, _, rest = str(uri).partition('://')
    return f'{scheme}://{rest.rstrip("/")}'

  @property
  def schemas(self) -> list[dict[str, str]]:
    """URI schemes served by the implementations loaded in this catalog."""
    return [{'scheme': scheme + '://',
             'implementation': (kind.func if hasattr(kind, 'func') else kind).__name__}
            for scheme, kind in self.location_types.items()]

  def _configured_row(self, uid: str | None) -> dict:
    if uid is None:
      return {'name': self.root, 'type': 'directory', 'size': 0,
              'gppu': {'uid': None, 'parent': None, 'locations': len(self.locations)}}
    return {'name': uid, 'type': 'directory', 'size': 0, 'gppu': deepcopy(self.locations[uid])}

  def _configured_listing(self, path, detail, recurse, refresh) -> list:
    if refresh:
      raise ValueError('reload configuration explicitly; catalog listing does not refresh storage')
    parent = None if path is None or path == self.root or path == '' else str(path)
    if parent is not None:
      self.locations[parent]
    result = []

    def children(uid):
      for child, owner in self._parents.items():
        if owner == uid:
          result.append(self._configured_row(child))
          if recurse:
            children(child)

    children(parent)
    return result if detail else [row['name'] for row in result]

  def _load(self) -> None:
    """Read the host's ``locations.yaml``; a Location whose ``index`` is not where gppufs keeps it is an error, not a redirect."""
    rows = yaml.safe_load((self.folder / 'locations.yaml').read_text(encoding='utf-8')) or []
    locations: dict[str, dict] = {}
    for row in rows:
      root = self.files._key(row['root_path'])
      if Path(row['index']) != Path(self.files._database_path(root)):
        raise ValueError(f"{row['root_path']}: catalog index {row['index']} is not {self.files._database_path(root)}")
      self._roots[row['root_path']] = root
      locations[row['root_path']] = row
    self.locations = locations
    by_id = {row['id']: row['root_path'] for row in rows}
    self._parents = {row['root_path']: by_id.get(row['parent_file_location_id']) for row in rows}

  def _location(self, path: str | Path) -> str:
    """The Location serving an absolute address: the deepest one whose root contains it."""
    physical = str(path).replace('\\', '/')
    if '://' not in physical and not Path(physical).is_absolute():
      raise ValueError(f'{path}: catalog addresses are absolute paths or URLs')
    key = self.files._key(path)
    owners = [location for location, root in self._roots.items() if GppuFileSystem._within(key, root)]
    if not owners:
      raise FileNotFoundError(f'{path}: not inside a catalog Location')
    location = max(owners, key=lambda location: len(self._roots[location]))
    if location not in self._split and self.files.fs.isdir(self._roots[location]):
      self.files.split(self._roots[location])   # a Location keeps its own index, where the catalog says it is
      self._split.add(location)
    return location

  def _parent(self, location: str) -> str:
    parent = self._parents[location]
    return self.root if parent is None else self._roots[parent]

  def _ancestors(self, path: str) -> Iterator[str]:
    parent = self._parents.get(path)
    while parent is not None:
      yield parent
      parent = self._parents.get(parent)

  def _catalog_row(self) -> dict:
    """The catalog: its Locations, how many have an index, and the totals and latest refresh their indexes hold.

    A Location below a Location whose totals are known is already inside them
    and is not counted again.
    """
    rows = {location: self._location_row(location)['gppu'] for location in self._roots}
    counted = [row for path, row in rows.items() if row['files'] is not None
      and not any(rows[parent]['files'] is not None for parent in self._ancestors(path))]
    spans = [TimeSpan(start=row['span'][0], end=row['span'][1]) for row in counted if row['span']]
    refreshed = [datetime.fromisoformat(row['probed_at']) for row in rows.values() if row['probed_at']]
    return {'name': self.root, 'type': 'directory', 'size': 0, 'gppu': {
      'name': self.catalog.name, 'path': self.root, 'parent': None, 'type': 'folder', 'modified_at': None,
      'handlers': [], 'files': sum(row['files'] for row in counted) if counted else None,
      'folders': sum(row['folders'] for row in counted) if counted else None,
      'bytes': sum(row['bytes'] for row in counted) if counted else None,
      'span': [str(min(span.start for span in spans)), str(max(span.end for span in spans))] if spans else None,
      'stats': {}, 'probed': False, 'probed_at': str(max(refreshed)) if refreshed else None, 'is_container': True,
      'locations': len(self.locations), 'indexed': sum(row['indexed'] for row in rows.values())}}

  def _location_row(self, location: str) -> dict:
    """A Location as the catalog knows it: the catalog's row, with the totals and last refresh its own index holds."""
    row, root = self.locations[location], self._roots[location]
    cached = self.files._stored(root)
    known = cached[0]['gppu'] if cached is not None else {}
    return {'name': root, 'type': 'directory', 'size': 0, 'gppu': {
      'name': PurePosixPath(root).name or root, 'path': root, 'parent': self._parent(location),
      'type': 'folder', 'modified_at': known.get('modified_at'), 'handlers': known.get('handlers', []),
      'files': known.get('files'), 'folders': known.get('folders'), 'bytes': known.get('bytes'),
      'span': known.get('span'), 'stats': known.get('stats', {}), 'probed': known.get('probed', False),
      'probed_at': known.get('probed_at'), 'is_container': True, 'indexed': cached is not None, 'location': row,
      **({'source': source} if (source := self._source(root)) is not None else {})}}

  def _source(self, path: str) -> dict | None:
    """What a folder is by the catalog: the canonical location it is a replica of on this host, or None."""
    return self._replicas.get(os.path.normcase(os.path.normpath(path)))

  def _served(self, location: str, row: dict) -> dict:
    """A row from a Location's folder: its root carries the catalog's parent and Location, a replica its source."""
    extra = {}
    if row['name'] == self._roots[location]:
      extra.update(parent=self._parent(location), location=self.locations[location])
    if row['type'] == 'directory' and (source := self._source(row['name'])) is not None:
      extra['source'] = source
    return {**row, 'gppu': {**row['gppu'], **extra}} if extra else row

  async def _info(self, path: str | Path | None = None, refresh: bool = False, **kwargs) -> dict:
    """The catalog itself, or one entry served by its Location: fsspec's ``info``; inside an event loop
    ``await catalog._info(path)``, read off the event loop either way."""
    return await asyncio.to_thread(self._entry, path, refresh)

  def _entry(self, path: str | Path | None = None, refresh: bool = False) -> dict:
    """``info`` on the calling thread, what ``_info`` runs off the event loop."""
    with self._lock:
      if self._configuration:
        if refresh:
          raise ValueError('reload configuration explicitly; catalog lookup does not refresh storage')
        uid = None if path is None or path == self.root or path == '' else str(path)
        return self._configured_row(uid)
      if path is None or path == self.root:
        if refresh:
          self._load()
        return self._catalog_row()
      location = self._location(path)
      return self._served(location, self.files._entry(path, refresh=refresh))

  async def _ls(self, path: str | Path | None = None, detail: bool = True,
                recurse: bool = False, refresh: bool = False, **kwargs) -> list:
    """The Locations at the catalog root, otherwise the listing the owning Location gives.

    fsspec's ``ls``; inside an event loop ``await catalog._ls(path)``, read off the event loop either way. ``refresh=True``
    at the root rereads ``locations.yaml``. Recursion from the root descends
    the Locations that have no parent Location; their subtrees hold the rest.
    """
    return await asyncio.to_thread(self._listing, path, detail, recurse, refresh)

  def _listing(self, path: str | Path | None = None, detail: bool = True,
               recurse: bool = False, refresh: bool = False) -> list:
    """``ls`` on the calling thread, what ``_ls`` runs off the event loop."""
    with self._lock:
      if self._configuration:
        return self._configured_listing(path, detail, recurse, refresh)
      if path is None or path == self.root:
        if refresh:
          self._load()
        result = []
        for location in sorted(self._roots, key=str.casefold):
          if recurse and self._parents[location] is not None:
            continue
          result.append(self._location_row(location))
          if recurse:
            result.extend(self.files._listing(self._roots[location], recurse=True))
      else:
        location = self._location(path)
        result = [self._served(location, row) for row in self.files._listing(path, recurse=recurse, refresh=refresh)]
      return result if detail else [row['name'] for row in result]

# endregion
# region Linked Data

class Drives(FileSystem):
    """gppufs's FileSystem in a Windows host's WSL: a file uri naming a drive, file://alex-pc/D:/Dev, is that drive as WSL mounts it,
    /mnt/d/Dev (`drives` in the app's configuration), so a location configured on the host is walked from its WSL as it is configured."""

    def local(self, uri: Any) -> Path:
        parsed = urlsplit(str(uri))
        path = unquote(parsed.path)
        if len(path) >= 3 and path[0] == '/' and path[2] == ':':
            if not (drives := glob('drives')):
                raise ValueError("`drives`, where WSL mounts this host's drives, is not in the app's configuration")
            uri = urlunsplit(parsed._replace(path=quote(f"{drives}/{path[1].casefold()}{path[3:]}")))
        return super().local(uri)


def catalog(records: list[dict], **location_types: Any) -> GppuCatalog:
    """gppufs's catalog of Linked Data's location records, the items of GET /fs/locations as the catalog's user read them: every location
    that has a uri, as a row of gppufs's configuration table, known by its id and reached by its uri (`meta.uri`), its data with its
    name (`meta.display_name`) and parent's id. One out of sight is not listed at all, and a location below one not listed is not
    listed either, since a location is part of the location above it; its connection is its root location, reached by the scheme of
    the root's uri. location_types are the Providers a caller adds by scheme, as GppuCatalog takes them; gppufs's FileSystem reaches
    file://, and in a Windows host's WSL, Drives does."""
    records = {r['id']: r for r in records if r['meta'].get('uri')}

    def root(r: dict) -> dict | None:
        """The root location above it; none when one above it is not listed, so it is not listed either."""
        while r['parent_id']:
            if not (r := records.get(r['parent_id'])):
                return None
        return r
    rows = [r['data'] | {'uid': r['id'], 'canonical': r['meta']['uri'], 'id': r['id'], 'name': r['meta'].get('display_name'),
                         'parent': r['parent_id'], 'connection': top['id']}
            for r in records.values() if (top := root(r))]
    connections = {r['uid']: {'kind': urlsplit(r['canonical']).scheme} for r in rows if r['connection'] == r['uid']}
    return GppuCatalog({'locations': rows, 'connections': connections}, location_types=location_types)


def here(catalog: GppuCatalog, uri: str) -> Path | None:
    """The folder on this host a location's file uri names, as the catalog's FileSystem reaches it (Drives in a Windows host's WSL);
    none when it names another host or is not a file uri. Which host is decided from the uri alone, as FileIndexer 0.1.3 decided it:
    another host's share is that host's location, and asking it from here waits out the network for every share that does not
    answer."""
    if urlsplit(uri).netloc.casefold() not in ('', socket.gethostname().split('.')[0].casefold()):
        return None
    try:
        return catalog.location_types['file']().local(uri)
    except ValueError:
        return None


def accessed(row: Mapping[str, Any]) -> Path | None:
    """The folder a location's handler says it is at on this host, `handler.access` by host (gppu.fs.files); none when it
    names none here."""
    access = (row.get('handler') or {}).get('access') or {}
    path = access.get(socket.gethostname().split('.')[0].casefold()) if isinstance(access, Mapping) else None
    return None if path is None else Path(path)


def reached(catalog: GppuCatalog) -> dict[str, dict[str, str]]:
    """The folders on this host the catalog's locations are: where its handler's access says, else where its file uri names, else
    below the folder of the location above it, by its uri below that one's; the location map locate() and resolve() take. Each is
    looked for once, so a caller reads it once."""
    found: dict[str, Path] = {}

    def folder(uid: str) -> Path | None:
        if uid not in found:
            row = catalog.locations[uid]
            path = accessed(row) or here(catalog, row['canonical'])
            if path is None and (parent := row.get('parent')) and (above := folder(parent)) is not None:
                rest = _below(str(catalog.locations[parent]['canonical']), str(row['canonical']))
                path = None if rest is None else above / unquote(rest)
            found[uid] = path
        return found[uid]
    return {full_path(path).as_posix(): {'location': uid, 'canonical': row['canonical']}
            for uid, row in catalog.locations.items() if (path := folder(uid)) is not None and path.is_dir()}


@functools.lru_cache(maxsize=4096)
def _on_host(folder: str) -> str:
    """A folder as the location map names folders: resolved, once for each folder."""
    return full_path(folder).as_posix()


def locate(folders: dict[str, dict[str, str]], row: dict[str, Any]) -> dict[str, Any]:
    """A gppufs row with the configured location it is in, the deepest of folders containing it: its location, its canonical
    address, the entry's address and its folder in it, and `location` among its handlers; outside them, the row as it is."""
    parent, _, name = row['name'].rpartition('/')
    here = f"{_on_host(parent).rstrip('/')}/{name}" if parent and name else _on_host(row['name'])
    base = max((folder for folder in folders if here == folder or here.startswith(folder.rstrip('/') + '/')), key=len, default=None)
    if base is None:
        return row
    location, folder = folders[base], '' if here == base else here[len(base.rstrip('/')) + 1:]
    found = {'location': str(location['location']), 'canonical': str(location['canonical']),
             'address': _address(str(location['canonical']), folder), 'folder': folder}
    return row | {'gppu': row['gppu'] | {'location': found, 'handlers': [*row['gppu']['handlers'], 'location']}}


def resolve(folders: dict[str, dict[str, str]], address: str) -> str:
    """The path on this host a configured location's address names, `sd://SD.agents/memory/MEMORY.md` among them, the deepest
    location winning; any other address as it is."""
    for folder, location in sorted(folders.items(), key=lambda item: len(str(item[1]['canonical'])), reverse=True):
        if (rest := _below(str(location['canonical']), address)) is not None:
            return posixpath.join(folder, rest) if rest else folder
    return address


# endregion
# region what is in the locations

PAGE = 1000   # the instances a listing asks Linked Data for at a time, so a folder of any size is never held whole
WHEN = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')   # how SharePoint gives a date or a time


def _json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f'{type(value).__name__} is not JSON')


def _text(value: Any) -> str:
    """A column's value as a file manager shows it: a date or a time as the local date it falls on, a whole number without
    decimals, a term by its label, a link by its description, a list joined."""
    if isinstance(value, dict):
        return str(value.get('Label') or value.get('Description') or '')
    if isinstance(value, list):
        return ', '.join(_text(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str) and WHEN.fullmatch(value):
        return datetime.fromisoformat(value).astimezone().date().isoformat()
    return '' if value is None else str(value)


def label(name: str) -> str:
    """A column's internal name, as SharePoint gives it, in words: _StartDate is Start Date, TaxYear is Tax Year."""
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name.replace('_x0020_', ' ').strip('_')).replace('_', ' ')


def paths(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Linked Data's locations by path, as the desktop shows them: each by its name, and by its name and uid where locations beside
    it share the name, as Windows shows one folder per name."""
    found = {row['id']: row for row in rows}
    names = Counter((row['parent'], row['name'].casefold()) for row in found.values())

    def path(row: dict[str, Any]) -> str:
        name = row['name'] if names[row['parent'], row['name'].casefold()] == 1 else f"{row['name']} ({row['id']})"
        return f"{path(found[row['parent']])}/{name}" if row['parent'] else name
    return {path(row): row for row in found.values()}


def where(tree: dict[str, dict[str, Any]], path: str) -> tuple[dict[str, Any] | None, str]:
    """The location a path is in, the longest location path in tree it starts with, and the path below it."""
    parts = [part for part in path.split('/') if part]
    for n in range(len(parts), 0, -1):
        if (location := tree.get('/'.join(parts[:n]))) is not None:
            return location, '/'.join(parts[n:])
    return None, path


INSTANCE_KINDS = ('symlink', 'junction', 'offline')   # what a copy is when nothing is read from it, its instance's meta.kind (Linked Data.md # FS)


def _earliest(*times: str | None) -> str | None:
    """The earliest of times given as ISO text."""
    given = [time for time in times if time]
    return min(given, key=lambda time: datetime.fromisoformat(time)) if given else None


def rows(index: Path) -> list[dict[str, Any]]:
    """What a gppufs index holds, read from a copy of it on this host, each row as the catalog keeps it, the folder's own first and
    every folder before what is in it: its gppufs id, which is its instance's, its path below the index's folder ('' for the
    folder itself), its file's type, the handler's, its instance's kind where nothing is read from it, when its source says it was
    created, and what its file and its instance hold."""
    import sqlite3
    with closing(sqlite3.connect(f'{index.as_uri()}?mode=ro', uri=True)) as db:
        held = db.execute('SELECT path, metadata FROM gppufs_entries').fetchall()
    found = []
    for path, metadata in held:
        row, path = json.loads(metadata), '' if path == '.' else path
        own = row['gppu']
        if not own.get('id'):
            raise ValueError(f'{index.name}: {path or "its folder"} has no id; gppufs gives every row one when it next writes the index')
        created = row.get('created_at') or (datetime.fromtimestamp(row['created']).astimezone().isoformat() if row.get('created') else None)
        handler = own['handlers'][0]
        found.append({'id': own['id'], 'path': path, 'type': 'file' if handler in INSTANCE_KINDS else handler,
                      'kind': handler if handler in INSTANCE_KINDS else None, 'created': created,
                      'file': {'kind': own['type'], 'size': own.get('size'), 'files': own.get('files'), 'folders': own.get('folders'),
                               'modified': own.get('modified_at'), 'created': created, 'content_type': row.get('content_type'),
                               'columns': row.get('columns') or {}},
                      'instance': {'size': own.get('size'), 'modified': own.get('modified_at')}})
    return sorted(found, key=lambda row: (row['path'].count('/') + bool(row['path']), row['path']))


class Catalog:
    """What is in Linked Data's locations: the catalog's database, Linked Data's fs, reached through its API by ld, a client whose
    base is Linked Data's /ld/v1. As Linked Data.md # FS has it, a file (fs.files) is what its instances are copies of, typed by the
    handler that reads it, a folder a file among them, and an instance (fs.instances) is one copy at one uri. Files make the tree:
    a file is inside the file of its folder (parent_id), a top folder's file inside the location whose uri it is; an instance is
    inside its file. The file of a copy under a location that a link (fs.links) links to another, a local synced folder to the
    cloud folder it copies, is at the linked location's uri and the same path below it, so every host's copy is an instance of the
    one file; elsewhere the file is at its instance's uri. Every index the Lake receives is loaded as the latest copy of its
    folder's, every file the Lake saves is recorded, and the catalog answers from the database alone. records reads Linked Data's
    location records, the items of GET /fs/locations."""

    def __init__(self, records: Callable[[], list[dict]], ld: Any) -> None:
        self.records = records
        self.ld = ld
        self._columns: list[str] | None = None   # columns(), read once and again after an m365 index is loaded
        self._received: dict[str, dict[str, Any]] = {}   # each folder whose index this process received, and how its load went
        self._guard = RLock()

    def _get(self, route: str, **params: Any) -> Any:
        r = self.ld.get(route, params=params)
        r.raise_for_status()
        return r.json()

    def _all(self, table: str, filters: dict[str, Any], **params: Any) -> Iterator[dict[str, Any]]:
        """The records of fs.files or fs.instances, table, that filters selects, a page at a time."""
        cursor = None
        while True:
            page = self._get(f'/fs/{table}', filters=json.dumps(filters), limit=PAGE, **params, **({'cursor': cursor} if cursor else {}))
            yield from page['items']
            if not (cursor := page.get('next')):
                return

    def _find(self, table: str, uri: str) -> dict[str, Any] | None:
        """The file or the instance at a uri; none when the catalog holds none."""
        items = self._get(f'/fs/{table}', filters=json.dumps({'meta.uri': {'$eq': uri}}), limit=1)['items']
        return items[0] if items else None

    def _under(self, table: str, uri: str) -> dict[str, dict[str, Any]]:
        """The files or the instances at a uri and below it, by their uris."""
        found = {r['meta']['uri']: r for r in self._all(table, {'meta.uri': {'$eq': uri}})}
        return found | {r['meta']['uri']: r for r in self._all(table, {'meta.uri': {'$startswith': uri.rstrip('/') + '/'}})}

    def _inside(self, id: str) -> Iterator[dict[str, Any]]:
        """The files directly inside one, by name."""
        return self._all('files', {'parent_id': {'$eq': id}}, sort='meta.display_name:asc')

    def _put(self, table: str, id: str, type: str, parent: str | None, uri: str, data: dict[str, Any],
             span: dict[str, Any] | None = None, kind: str | None = None) -> None:
        name = PurePosixPath(urlsplit(uri).path).name or urlsplit(uri).netloc
        meta = {'uri': uri, 'display_name': name, 'status': 'active'} | ({'kind': kind} if kind else {})
        self.ld.put(f'/fs/{table}/{id}', json={'type': type, 'parent_id': parent, 'data': data, 'span': span,
                                               'meta': meta}).raise_for_status()

    def _delete(self, table: str, id: str) -> None:
        self.ld.delete(f'/fs/{table}/{id}').raise_for_status()

    def _linked(self) -> dict[str, str]:
        """Each location a link links to another, by its uri, the linked location's uri: a local synced folder's cloud folder."""
        by_id = {r['id']: r['meta'].get('uri') for r in self.records()}
        cursor, linked = None, {}
        while True:
            page = self._get('/fs/links', limit=PAGE, **({'cursor': cursor} if cursor else {}))
            for link in page['items']:
                if by_id.get(link['from_id']) and by_id.get(link['to_id']):
                    linked[by_id[link['from_id']].rstrip('/')] = by_id[link['to_id']].rstrip('/')
            if not (cursor := page.get('next')):
                return linked

    def file_of(self, uri: str, linked: dict[str, str] | None = None) -> str:
        """The uri of the file a copy at uri is an instance of: below the deepest location at or above it that is linked to
        another, the linked location's uri and the same path below it; elsewhere uri itself."""
        linked = self._linked() if linked is None else linked
        for local in sorted(linked, key=len, reverse=True):
            if (below := _below(local, uri)) is not None:
                return _address(linked[local], below)
        return uri

    def _parent(self, uri: str) -> str | None:
        """The id of what the file at a uri is inside: the location whose uri it is, else the file of the folder holding it, made
        when the catalog holds none; none at the top of its host or tenant, where no location is."""
        by_uri = {r['meta']['uri'].rstrip('/'): r['id'] for r in self.records() if r['meta'].get('uri')}
        if (location := by_uri.get(uri.rstrip('/'))) is not None:
            return location
        above = uri.rstrip('/').rpartition('/')[0]
        if urlsplit(above).path in ('', '/') and above.rstrip('/') not in by_uri:
            return None
        if (found := self._find('files', above)) is not None:
            return found['id']
        made = str(uuid_create(0x1002))
        self._put('files', made, 'folder', self._parent(above), above, {'kind': 'folder'})
        return made

    def _orphans(self, files: dict[str, str]) -> None:
        """Of files, ids by uri, each left with no instance and no file inside it deleted, the deepest first."""
        for uri, id in sorted(files.items(), key=lambda item: len(item[0]), reverse=True):
            if not self._get('/fs/instances', filters=json.dumps({'parent_id': {'$eq': id}}), limit=1)['items'] \
                    and not self._get('/fs/files', filters=json.dumps({'parent_id': {'$eq': id}}), limit=1)['items']:
                self._delete('files', id)

    def load(self, source: str, copy: Path) -> None:
        """An index the Lake received, copy on this host, loaded as the latest copy of its folder's: source is the uri it came from,
        its folder's uri as Linked Data names it and the index's name (FileIndexer's store.send). Each row is put as its instance,
        by its gppufs id, inside its file, which is found by its uri or made once; what the folder's earlier copy held and this one
        does not is deleted, and a file left with no instance with it. An index whose rows have no ids is refused. How the load goes
        is kept for loaded()."""
        folder = self.received(source)
        try:
            self._load(folder, copy)
        except BaseException as error:
            with self._guard:
                self._received[folder] |= {'loading': False, 'error': f'{type(error).__name__}: {error}'}
            raise
        with self._guard:
            self._received[folder] |= {'loading': False, 'error': None}

    def received(self, source: str) -> str:
        """An index from source received, its load to come, and the folder it is of; loaded() answers it as loading until it is
        loaded."""
        folder = source.rpartition('/')[0]
        with self._guard:
            if not self._received.get(folder, {}).get('loading'):
                self._received[folder] = {'received': datetime.now().astimezone().isoformat(), 'loading': True, 'error': None}
        return folder

    def _load(self, folder: str, copy: Path) -> None:
        held = rows(copy)
        if not held or held[0]['path']:
            raise ValueError(f'{folder}: the index holds no row for its folder')
        top = self.file_of(folder)
        files, instances = self._under('files', top), self._under('instances', folder)
        loaded = datetime.now().astimezone().isoformat()
        ids: dict[str, str] = {}   # each row's path -> its file's id
        for row in held:
            path = row['path']
            uri = _address(top, path)
            found = files.get(uri)
            ids[path] = found['id'] if found else str(uuid_create(0x1002))
            start = _earliest(row['created'], ((found or {}).get('span') or {}).get('start'))
            self._put('files', ids[path], row['type'], self._parent(top) if not path else ids[path.rpartition('/')[0]], uri,
                      row['file'], span={'start': start, 'end': None, 'bounds': '[)'} if start else None)
            self._put('instances', row['id'], 'instance', ids[path], _address(folder, path),
                      row['instance'] | {'index': folder} | ({} if path else {'loaded': loaded}), kind=row['kind'])
        kept, left = {row['id'] for row in held}, {}
        for instance in instances.values():
            if instance['data'].get('index') == folder and instance['id'] not in kept:   # gone from the latest copy
                self._delete('instances', instance['id'])
                left[instance['meta']['uri']] = instance['parent_id']
        self._orphans({self.file_of(uri): id for uri, id in left.items()})
        if urlsplit(top).scheme == 'm365':
            self._columns = None

    def record(self, uri: str, type: str, data: dict[str, Any]) -> dict[str, Any]:
        """A file the Lake holds at uri recorded as what its handler read, type and data: its file and its instance, each keeping
        the record the catalog has for it; the file as the catalog lists it."""
        file, instance = self._find('files', uri), self._find('instances', uri)
        id = file['id'] if file else str(uuid_create(0x1002))
        self._put('files', id, type, file['parent_id'] if file else self._parent(uri), uri, data)
        self._put('instances', instance['id'] if instance else str(uuid_create(0x1003)), 'instance', id, uri,
                  {'size': data.get('size'), 'modified': data.get('modified')})
        return self.info(uri)

    def locations(self) -> list[dict[str, Any]]:
        """Linked Data's locations the catalog holds the folder of, with every location above them, so they make one tree: each
        its id, name, canonical address, parent's id and whether the catalog holds its folder."""
        records = {r['id']: r for r in self.records() if r['meta'].get('uri')}
        linked = self._linked()
        indexed = {id for id, r in records.items() if self._find('files', self.file_of(r['meta']['uri'], linked)) is not None}
        kept: set[str] = set()
        for id in indexed:
            while id in records and id not in kept:
                kept.add(id)
                id = records[id]['parent_id']
        return [{'id': id, 'name': records[id]['meta'].get('display_name'), 'canonical': records[id]['meta']['uri'],
                 'parent': records[id]['parent_id'] if records[id]['parent_id'] in kept else None, 'indexed': id in indexed}
                for id in kept]

    def columns(self) -> list[str]:
        """The columns an entry is described by, by their internal names: its content type, then each column SharePoint gave some
        of its items and not every one, those carried most first. Every item carries SharePoint's own columns, its file name, its
        version, who edited it; what only some carry is what a library or a content type adds, a statement's period, a tax form's
        year. Read from every m365 file, the store whose listing carries them."""
        if self._columns is None:
            counted, items = Counter(), 0
            for file in self._all('files', {'meta.uri': {'$startswith': 'm365://'}}):
                if held := file['data'].get('columns'):
                    items += 1
                    counted.update(held.keys())
            self._columns = ['ContentType'] + [name for name, n in sorted(counted.items(), key=lambda c: (-c[1], c[0])) if n < items]
        return self._columns

    def _entry(self, file: dict[str, Any]) -> dict[str, Any]:
        """A file as the catalog lists it: its id, kind, name, size, totals, when it was modified and created, and its content type
        and the text of its columns where its store gave them."""
        data, held = file['data'], file['data'].get('columns') or {}
        return {'id': file['id'], 'kind': data.get('kind'), 'name': file['meta'].get('display_name'), 'size': data.get('size'),
                'files': data.get('files'), 'folders': data.get('folders'), 'modified': data.get('modified'), 'created': data.get('created'),
                'content_type': data.get('content_type'),
                'columns': {name: text for name in self.columns() if (text := _text(held.get(name)))}}

    def _uri(self, location: str) -> str:
        """A location's uri, by its Linked Data id."""
        for r in self.records():
            if r['id'] == location and r['meta'].get('uri'):
                return r['meta']['uri']
        raise LookupError(f'location {location}: Linked Data has no location with a uri by that id')

    def _held(self, uri: str) -> dict[str, Any]:
        """The file a copy at uri is an instance of."""
        if (found := self._find('files', self.file_of(uri))) is None:
            raise LookupError(f'{uri}: the catalog holds nothing there')
        return found

    def entries(self, location: str | None = None, parent: UUID | None = None, path: str | None = None,
                uri: str | None = None) -> Iterator[dict[str, Any]]:
        """What is directly inside a file, parent, at a location's root, in the folder a path names as the desktop shows the
        catalog, or at a uri, by name, each with the text of its columns. What is asked for is found before the first row is."""
        if parent is not None:
            id = self.entry(parent)['id']
        elif path is not None:
            if not path.strip('/'):
                return iter(())   # the catalog's root holds only locations
            found, below = where(paths(self.locations()), path)
            if found is None:
                raise LookupError(f'{path}: the catalog holds no location there')
            if not below and not found['indexed']:
                return iter(())
            id = self._held(_address(found['canonical'], below))['id']
        else:
            id = self._held(uri if uri is not None else self._uri(location))['id']
        return (self._entry(file) for file in self._inside(id))

    def at(self, location: str, path: str) -> UUID:
        """The id of the file path names below a location's root."""
        if not path.strip('/'):
            raise LookupError(f'location {location}: an empty path names its root, which is no entry')
        return UUID(self._held(_address(self._uri(location), path.strip('/')))['id'])

    def entry(self, uid: UUID) -> dict[str, Any]:
        """One file by its id, with its uri, the id of what it is inside and its handler's type."""
        r = self.ld.get(f'/fs/files/{uid}')
        if r.status_code == 404 or (r.is_success and r.json()['flags'] & 4):
            raise LookupError(f'entry {uid}: the catalog holds no such entry')
        r.raise_for_status()
        file = r.json()
        return self._entry(file) | {'uri': file['meta'].get('uri'), 'parent': file['parent_id'], 'type': file['type'],
                                    'span': file['span']}

    def info(self, uri: str) -> dict[str, Any]:
        """The file a copy at uri is an instance of, as entry() answers it."""
        return self.entry(UUID(self._held(uri)['id']))

    def instances(self, uri: str) -> list[dict[str, Any]]:
        """The copies of the file a copy at uri is an instance of: each its id, uri and kind, and the folder whose index it came from."""
        return [{'id': r['id'], 'uri': r['meta'].get('uri'), 'kind': r['meta'].get('kind'), 'index': r['data'].get('index')}
                for r in self._all('instances', {'parent_id': {'$eq': self._held(uri)['id']}})]

    def loaded(self, folder: str) -> dict[str, Any]:
        """The copy of a folder's index the catalog holds and the one it received last: when it was loaded, from the database; when
        this process received one, whether it is still loading and why its load failed. An indexer sends an index written since
        the copy it received, or one the catalog lacks."""
        found = self._find('instances', folder)
        held = found is not None and found['data'].get('index') == folder
        with self._guard:
            state = dict(self._received.get(folder, {}))
        if not held and not state:
            raise LookupError(f'{folder}: the catalog holds no index of it')
        return {'folder': folder, 'loaded': found['data']['loaded'] if held else None, 'received': state.get('received'),
                'loading': state.get('loading', False), 'error': state.get('error')}

    def unload(self, folder: str) -> None:
        """Everything a folder's index put in the catalog deleted: its instances, and each file left with no instance, as when the
        folder is no longer indexed."""
        left = {}
        for instance in self._under('instances', folder).values():
            if instance['data'].get('index') == folder:
                self._delete('instances', instance['id'])
                left[instance['meta']['uri']] = instance['parent_id']
        if not left:
            raise LookupError(f'{folder}: the catalog holds no index of it')
        self._orphans({self.file_of(uri): id for uri, id in left.items()})

    def forget(self, uri: str) -> None:
        """The file the Lake held at a uri, removed from there, deleted from the catalog: its instance, and its file with it."""
        instance = self._find('instances', uri)
        if instance is None:
            raise LookupError(f'{uri}: the catalog holds nothing there')
        self._delete('instances', instance['id'])
        self._orphans({self.file_of(uri): instance['parent_id']})


def api(catalog: Catalog):
    """catalog as REST resources, a FastAPI app an APIApp serves at /lake/catalog, mounted before the Lake's at /lake, whose paths
    are uris and would take it. Needs FastAPI (the `ld` extra).

    GET /locations                  Linked Data's locations the catalog holds the folder of, as one tree
    GET /locations/{id}/entries     what is at a location's root, a line of JSON each, by name
    GET /locations/{id}/entry?path= the entry path names below a location's root
    GET /entries/{uid}              one entry by its gppufs id
    GET /entries/{uid}/entries      what is directly inside an entry, a line of JSON each, by name
    GET /entries?path=              what is directly inside the folder path names as the desktop shows the catalog, a line each
    GET /columns                    the columns an entry is described by, each its internal name and its name in words
    GET /indexes?folder=            the copy of the index of the folder a uri names the catalog holds, and the one it received last

    An entry listed carries the text of its columns. What the catalog does not hold answers 404 with its error."""
    from fastapi import FastAPI, Response
    from fastapi.responses import StreamingResponse

    def reply(payload: Any, status: int = 200) -> Response:
        return Response(json.dumps(payload, default=_json, ensure_ascii=False), status_code=status, media_type='application/json; charset=utf-8')

    def lines(rows: Iterator[dict[str, Any]]) -> StreamingResponse:
        return StreamingResponse((json.dumps(row, default=_json, ensure_ascii=False) + '\n' for row in rows),
                                 media_type='application/x-ndjson; charset=utf-8')   # as a client takes text without one differs

    app = FastAPI(title='Catalog')
    app.add_exception_handler(LookupError, lambda request, error: reply({'error': str(error)}, 404))

    @app.get('/locations')
    def locations():
        return reply(catalog.locations())

    @app.get('/locations/{id}/entries')
    def at_root(id: str):
        return lines(catalog.entries(location=id))

    @app.get('/locations/{id}/entry')
    def entry_at(id: str, path: str):
        return reply(catalog.entry(catalog.at(id, path)))

    @app.get('/entries/{uid}')
    def entry(uid: UUID):
        return reply(catalog.entry(uid))

    @app.get('/entries/{uid}/entries')
    def inside(uid: UUID):
        return lines(catalog.entries(parent=uid))

    @app.get('/entries')
    def at_path(path: str):
        return lines(catalog.entries(path=path))

    @app.get('/columns')
    def columns():
        return reply([{'name': name, 'label': label(name)} for name in catalog.columns()])

    @app.get('/indexes')
    def indexes(folder: str):
        return reply(catalog.loaded(folder))

    return app


def _seconds(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


class CatalogFileSystem(AbstractFileSystem):
    """The catalog through its API, an fsspec filesystem: Linked Data's locations are folders, each under the one above it, and in
    each is what the catalog holds at its root. ls reads a folder a line at a time, by its path, and keeps what it read, which info
    answers from; an entry is shown modified when its source last changed it and created when its source says it was.
    A path is the catalog's own, or the address of what a location holds, `m365://karelin/sharepoint/...`, read as its location's
    path and the path below it. Read-only: the catalog holds what an entry is, and its bytes are what the Lake gives at the entry's
    address. client is the API's, made from url, or one a caller gives, such as a test's."""

    protocol = 'catalog'
    cachable = False

    def __init__(self, url: str = '', client: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        import httpx
        self.client = client or httpx.Client(base_url=url.rstrip('/'), timeout=300)
        self._tree: dict[str, dict[str, Any]] | None = None   # Linked Data's locations by path, read once
        self._listed: dict[str, dict[str, dict[str, Any]]] = {}   # each folder listed -> its entries by name

    def _get(self, route: str, **params: str):
        r = self.client.get(f"/lake/catalog{route}", params=params)
        if r.status_code == 404:
            raise FileNotFoundError(f'{route}: {r.text}')
        r.raise_for_status()
        return r

    def _locations(self) -> dict[str, dict[str, Any]]:
        """Linked Data's locations by path, read once."""
        if self._tree is None:
            self._tree = paths(self._get('/locations').json())
        return self._tree

    def _where(self, path: str) -> tuple[dict[str, Any] | None, str]:
        return where(self._locations(), path)

    def _named(self, path: str) -> str:
        """A path as the catalog shows it: an address as the path of the location whose canonical address holds it, the deepest,
        and the path below that; the catalog's own path as it is."""
        path = self._strip_protocol(path)
        if split_protocol(path)[0] is None:
            return path.strip('/')
        for key, location in sorted(self._locations().items(), key=lambda item: len(item[1].get('canonical') or ''), reverse=True):
            if location.get('canonical') and (below := _below(location['canonical'], path)) is not None:
                return f'{key}/{below}' if below else key
        raise FileNotFoundError(f'{path}: no location of the catalog holds it')

    @staticmethod
    def _entry(row: dict[str, Any], name: str) -> dict[str, Any]:
        """A catalog row as fsspec has an entry; its gppufs id is `id`, since a FUSE bridge reads `uid` as the owner's."""
        folder = row['kind'] == 'folder'
        entry = {'name': name, 'type': 'directory' if folder else 'file', 'size': 0 if folder else row['size'] or 0,
                 'id': row['id'], 'content_type': row['content_type'], 'columns': row['columns']}
        for key, value in (('mtime', row['modified']), ('ctime', row['created'])):
            if value:
                entry[key] = _seconds(value)
        return entry

    def ls(self, path: str = '', detail: bool = True, **kwargs: Any) -> list[dict[str, Any]] | list[str]:
        path = self._named(path)
        location, below = self._where(path)
        rows = [{'name': key, 'type': 'directory', 'size': 0} for key in self._locations()
                if key.rpartition('/')[0] == path and key != path]
        if location is not None and (below or location['indexed']):
            listed = {}
            with self.client.stream("GET", "/lake/catalog/entries", params={'path': path}) as r:
                if r.status_code == 404:
                    raise FileNotFoundError(f'{path}: {r.read().decode()}')
                r.raise_for_status()
                for line in r.iter_lines():
                    row = json.loads(line)
                    listed[row['name']] = self._entry(row, f"{path}/{row['name']}")
            self._listed[path] = listed
            rows += listed.values()
        elif location is None and path:
            raise FileNotFoundError(path)
        return rows if detail else [row['name'] for row in rows]

    def info(self, path: str = '', **kwargs: Any) -> dict[str, Any]:
        path = self._named(path)
        if not path or path in self._locations():
            return {'name': path, 'type': 'directory', 'size': 0}
        folder, _, name = path.rpartition('/')
        if folder not in self._listed:
            self.ls(folder)
        if name not in self._listed[folder]:
            raise FileNotFoundError(path)
        return self._listed[folder][name]

    def _open(self, path: str, mode: str = 'rb', **kwargs: Any):
        """The bytes of an entry, as the Lake gives them at its address: its location's canonical address and its path there."""
        if mode != 'rb':
            raise PermissionError(f'{path}: the catalog is read-only')
        path = self._named(path)
        location, below = self._where(path)
        if location is None or not below or not location.get('canonical'):
            raise FileNotFoundError(f'{path}: the catalog holds no entry with an address there')
        from .lake import LakeFileSystem   # the Lake's module imports the catalog's
        return LakeFileSystem(root=_address(location['canonical'], below), client=self.client)._open('', mode)

# endregion
