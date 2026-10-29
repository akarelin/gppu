r"""gppufs: DataObjects in Containers, Containers in Locations.

A Location is one place in the configured hierarchy, known by its uid. A Container holds alike objects and takes
paths relative to itself. A Provider reaches objects by uri over one connection, and an instance of it is that Connection:
FileSystem is the Provider of files, and M365, Telegram and Plaud are Providers in CRAP. A DataObject is content
with its uri.

The public methods are the API. The Lake, which saves objects and retrieves them by uri, is gppu.fs.lake.

Files:
``GppuFileSystem(location)`` is the fsspec file system of a location, with a SQLite index beside each folder it lists. ``ls`` and
``info`` identify an entry from its listing, by :func:`gppu.fs.handlers.probe` on this host, and read nothing; ``refresh=True`` parses
it with the handler :mod:`gppu.fs.handlers` gives it, and a row carries the handler's Record under ``gppu.record``. A file a handler
reads on a store other than this host is fetched into the cache, one at a time, and removed. An archive is opened only when it is
listed itself; a recursion enters folders, never an ignored one, and an archive only when the index holds its listing. An
ignored file is neither indexed nor listed.

Public I/O calls decorated with :func:`gppu.sync` return directly outside an event loop and are awaitable inside one; their
``*_sync`` methods run on the calling thread. All local paths are resolved by :func:`gppu.full_path`.
"""
from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO
from urllib.parse import quote, unquote, urlsplit

import yaml
from fsspec import open as open_uri, register_implementation
from fsspec.archive import AbstractArchiveFileSystem
from fsspec.spec import AbstractFileSystem

from ..gppu import TimeSpan, OSType, TemplateSet, detect_os, full_path, y2path, y2uri
from . import handlers


# region providers

# The file in a folder that says what a write may do to the files it holds: a list of update, upsert, delete.
MERGE_RULES = '.merge.yaml'
OPERATIONS = ('update', 'upsert', 'delete')

@dataclass(frozen=True)
class DataObject:
  """Content and the uri it was read from or is written to.

  A DataObject is a value. Its content is JSON, text, bytes or a binary stream, and its structure belongs to the source.

  Attributes:
    uri (y2uri): The uri of the object at its source.
    content (dict[str, Any] | list[Any] | str | int | float | bool | None | bytes | BinaryIO): What the object holds.
    identity (str | None): The id the source gives the object, or None when it gives none.
    kind (str): What sort of object the source says it is; object when it says nothing.
    name (str): The object's name, used by naming templates.
    parent (DataObject | None): The object this one belongs to, such as the list a task is in.
    removed (bool): True when a refresh reports the object as gone from its source.
  """
  uri: y2uri
  content: dict[str, Any] | list[Any] | str | int | float | bool | None | bytes | BinaryIO
  identity: str | None
  kind: str = 'object'
  name: str = ''
  parent: 'DataObject | None' = None
  removed: bool = False

  def __post_init__(self) -> None:
    object.__setattr__(self, 'uri', y2uri(self.uri))


def _join(uri: y2uri | str, path: y2path | str) -> y2uri:
  """uri with a relative path below it, each name uri-escaped; a canonical uri's trailing slash is its own, not the path's."""
  uri = y2uri(uri)
  if not str(path):
    return uri
  joined = uri / quote(str(path), safe='/')
  joined._last_segment_empty = False
  return joined


def _address(canonical: str, rest: str) -> str:
  """The address of rest below a canonical uri, its names as they are, as an index row carries it; a canonical uri ending
  in `/`, a scheme's root (`work://`) among them, has rest right after it."""
  return canonical if not rest else canonical + rest if canonical.endswith('/') else f'{canonical}/{rest}'


def _below(canonical: str, address: str) -> str | None:
  """What an address names below a canonical uri, empty for the canonical uri itself; none when it is not at or below it."""
  if address.rstrip('/') == canonical.rstrip('/'):
    return ''
  base = canonical if canonical.endswith('/') else canonical + '/'
  return address[len(base):].strip('/') if address.startswith(base) else None


class Provider:
  """Reaches objects by their uri over one connection.

  An instance is a Connection: the Provider with its connection parameters. The same connection that reads a
  Container's objects is the one that finds the Locations below a tenant, so one instance does both and holds the
  session and credentials once. FileSystem is the Provider of files;
  M365, Telegram and Plaud are Providers written in CRAP. A Provider that cannot write raises PermissionError from
  write and delete. Container and Location call these methods; nothing else needs to.

  Attributes:
    scheme (str): The uri scheme this Provider reaches: file, m365, telegram, plaud.
    connection (dict[str, Any]): The connection parameters it was constructed with: host, account, credentials.
  """
  scheme = ''

  def __init__(self, connection: Mapping[str, Any] | None = None) -> None:
    self.connection = deepcopy(dict(connection)) if connection is not None else {}

  def join(self, uri: y2uri, path: y2path | str) -> y2uri:
    """The uri of path below uri. Each name is uri-escaped; a Provider whose paths are already escaped ids joins
    them as they are."""
    return _join(uri, path)

  def ls(self, uri: y2uri) -> list[dict[str, Any]]:
    """What is directly inside uri, each entry named by its own name with its type and size."""
    raise NotImplementedError(f'{self.scheme}: ls is not implemented')

  def info(self, uri: y2uri) -> dict[str, Any]:
    """What is known about the object at uri without reading its content."""
    raise NotImplementedError(f'{self.scheme}: info is not implemented')

  def open(self, uri: y2uri, mode: str = 'rb') -> BinaryIO:
    """The bytes of the object at uri."""
    raise NotImplementedError(f'{self.scheme}: open is not implemented')

  def read(self, uri: y2uri) -> DataObject:
    """The object at uri with its content."""
    raise NotImplementedError(f'{self.scheme}: read is not implemented')

  def write(self, uri: y2uri, obj: DataObject, *, replace: bool | Callable[[], bool] = False) -> None:
    """Store obj's content at uri. A held object that differs is replaced only when replace is true or, called
    once the conflict is known, returns true."""
    raise PermissionError(f'{self.scheme}: objects are read-only')

  def delete(self, uri: y2uri) -> None:
    """Remove the object at uri."""
    raise PermissionError(f'{self.scheme}: objects are read-only')

  def walk(self, uri: y2uri, path: y2path | str = '', *, level: str = 'files', recursive: bool = False,
           boundaries: Iterable[y2path | str] = ()) -> Iterator[tuple[dict, list[dict]]]:
    """Each folder at and below path under uri, with the entries it holds; paths stay relative to uri.

    A boundary is reported and never entered. The default reads each entry through ls and, at the handlers level,
    read; FileSystem reads files through its handlers instead.
    """
    yield from walk_container(Container(self, uri), str(path), level, recursive, boundaries)

  @contextmanager
  def refresh(self, state: dict[str, Any], uri: y2uri) -> Iterator[tuple[Iterator[DataObject], Callable[[], None]]]:
    """The objects changed at or below uri since state was recorded, and a callback that records the new state."""
    raise NotImplementedError(f'{self.scheme}: refresh is not implemented')
    yield

  def locations(self, uri: y2uri) -> list[tuple[str, str]]:
    """The Locations found directly below the Location at uri, as their path below it and their name.

    A tenant lists its users and a user lists their mailbox parts; a Provider with nothing to discover lists none.
    """
    return []


class Container:
  """Alike objects kept together under one uri and reached through one Provider: a folder, a git repo, a
  SharePoint file collection, an index file.

  A Container takes paths relative to itself and never a uri. Its Provider does the reading and writing; the
  Container adds paths and naming templates, so one Container serves every Provider.

  Attributes:
    provider (Provider): The Provider that reaches its objects.
    uri (y2uri): The uri of the Container itself.
  """

  def __init__(self, provider: Provider, uri: y2uri | str, *, templates: Mapping[str, str] | None = None) -> None:
    """A Container at uri, reached through provider. templates name where a DataObject belongs: filename, the
    parent object's kinds, date, identity and collision."""
    self.provider = provider
    self.uri = y2uri(uri)
    self.templates = None if templates is None else TemplateSet(named={'objects': deepcopy(dict(templates))})
    self._paths: dict[str, str] | None = None
    self._identities: dict[str, str] = {}
    self._rules: dict[str, frozenset[str] | None] = {}

  def _uri(self, path: y2path | str) -> y2uri:
    return self.provider.join(self.uri, Location.relative(path))

  def ls(self, path: y2path | str = '', detail: bool = True) -> list[dict[str, Any]] | list[str]:
    """What is directly inside path, each entry named by its path in this Container, with type and size.

    Callers: FileIndexer, the Plaud Dagster job, admin_ui.

    Args:
      path (y2path | str): Relative directory path; empty selects the Container root.
      detail (bool): True returns metadata objects; false returns only paths.

    Returns:
      list[dict] | list[str]: Immediate children. Detailed entries contain name relative to the Container, type and size, plus Provider metadata; otherwise entries are relative path strings.
    """
    path = str(Location.relative(path))
    rows = [row | {'name': f"{path}/{row['name']}" if path else row['name']}
            for row in self.provider.ls(self._uri(path))]
    return rows if detail else [row['name'] for row in rows]

  def walk(self, path: y2path | str = '', *, level: str = 'files', recursive: bool = False,
           boundaries: Iterable[y2path | str] = ()) -> Iterator[tuple[dict, list[dict]]]:
    """Each folder at and below path with what it holds, read as deep as level: refresh, files, handlers or archives.

    A boundary path is reported and not entered. A listing error is raised, never read as an empty folder.
    Caller: FileIndexer.

    Args:
      path (y2path | str): Relative starting path; empty selects the Container root.
      level (str): Reading depth: refresh, files, handlers or archives.
      recursive (bool): Whether to descend into child directories.
      boundaries (Iterable[y2path | str]): Relative paths to report without entering.

    Returns:
      Iterator[tuple[dict, list[dict]]]: Pairs of folder metadata and immediate child metadata. Entries contain name, type and Provider/handler fields; boundary marks a reported traversal boundary.
    """
    yield from self.provider.walk(self.uri, path, level=level, recursive=recursive, boundaries=boundaries)

  def info(self, path: y2path | str = '') -> dict[str, Any]:
    """The record of path, as its Provider gives it.

    Args:
      path (y2path | str): Relative object path; empty selects the Container root.

    Returns:
      dict: The object's record as its Provider gives it, without its content.
    """
    return self.provider.info(self._uri(path))

  def open(self, path: y2path | str, mode: str = 'rb') -> BinaryIO:
    """The bytes at path. Caller: admin_ui.

    Args:
      path (y2path | str): Relative object path.
      mode (str): Stream mode passed to the Provider; rb reads bytes.

    Returns:
      BinaryIO: Open stream owned and closed by the caller.
    """
    return self.provider.open(self._uri(path), mode)

  def read(self, path: y2path | str | DataObject) -> DataObject:
    """The object at path with its content.

    Given a DataObject, the path is where the naming templates put it, and the result keeps its uri and identity.
    An object whose source gives no identity is identified by its path. Callers: Dagster jobs, admin_ui.

    Args:
      path (y2path | str | DataObject): Relative object path, or a DataObject whose stored path is resolved from naming templates.

    Returns:
      DataObject: Object with uri, identity, kind, name and content. A supplied DataObject retains its identity and URI; a path read uses its relative path when the Provider supplies no identity.
    """
    if isinstance(path, DataObject):
      obj, path = path, self.path_of(path)
      uri = self._uri(path)
      binary = isinstance(obj.content, bytes) or hasattr(obj.content, 'read')
      content = self.provider.open(uri) if binary else self.provider.read(uri).content
      return replace(obj, content=content, name=PurePosixPath(str(path)).name)
    obj = self.provider.read(self._uri(path))
    return obj if obj.identity is not None else replace(obj, identity=str(path))

  def write(self, path: y2path | str, obj: DataObject) -> None:
    """Store obj at path by the rules of its folder. The object's uri is unchanged.

    A new object is written and a held one that matches, or that the new bytes strictly extend, is left to the
    Provider. Any other change to a held file, and a removed object, is what the nearest .merge.yaml at or above
    the object's folder in this Container permits: update or upsert replaces the held file, delete removes the file
    of a removed object. Without a permitting rule a changed file raises FileExistsError and a removed object's
    file is kept. With an identity template, a path already holding another object's identity is
    refused. Callers: Dagster jobs, Cruft pipelines.

    Args:
      path (y2path | str): Nonempty relative destination path.
      obj (DataObject): Object supplying content and identity for the Provider write.

    Returns:
      None: The Provider stores the object; conflicting stored identity raises ValueError.
    """
    if not isinstance(obj, DataObject):
      raise TypeError('Container.write requires a DataObject')
    if not isinstance(path, (y2path, str)):
      raise TypeError('Container.write requires a relative path')
    path = str(Location.relative(path))
    if not path:
      raise ValueError('Container write path must name an object')
    uri = self._uri(path)
    if obj.removed:
      if 'delete' in self.rules(path):
        try:
          self.delete(path)
        except FileNotFoundError:
          pass  # the source removed an object this folder never held
      return
    binary = isinstance(obj.content, bytes) or hasattr(obj.content, 'read')
    if not binary and self.templates is not None and 'identity' in self.templates.named:
      identity = self.templates.render_template('identity', uri=str(obj.uri), it=obj.content, path=path)
      if identity is not None:
        try:
          held = self.provider.read(uri).content
        except FileNotFoundError:
          held = None
        if held is not None and identity != self.templates.render_template('identity', uri=str(obj.uri), it=held, path=path):
          raise ValueError(f'{uri}: refusing to replace a different object identity')
    self.provider.write(uri, obj, replace=lambda: bool(self.rules(path) & {'update', 'upsert'}))

  def rules(self, path: y2path | str) -> frozenset[str]:
    """What a write may do at path: the operations the nearest .merge.yaml at or above its folder lists, read once
    per folder. Empty when no folder up to this Container's root has one.

    Args:
      path (y2path | str): Relative object path.

    Returns:
      frozenset[str]: update, upsert and delete as listed; a rule naming anything else raises ValueError.
    """
    folder = PurePosixPath(str(Location.relative(path))).parent
    for at in (str(folder) for folder in (folder, *folder.parents)):
      if at not in self._rules:
        uri = self._uri(MERGE_RULES if at == '.' else f'{at}/{MERGE_RULES}')
        try:
          with self.provider.open(uri) as stream:
            listed = yaml.safe_load(stream) or []
        except FileNotFoundError:
          listed = None
        if listed is not None and (not isinstance(listed, list) or any(operation not in OPERATIONS for operation in listed)):
          raise ValueError(f'{uri}: a merge rule lists operations from {", ".join(OPERATIONS)}; others are not specified')
        self._rules[at] = None if listed is None else frozenset(listed)
      if self._rules[at] is not None:
        return self._rules[at]
    return frozenset()

  def delete(self, path: y2path | str) -> None:
    """Remove the object at path. Caller: Dagster jobs, before rewriting an object.

    Args:
      path (y2path | str): Relative object path to remove.

    Returns:
      None: The Provider removes the object and any cached path-to-identity entry is invalidated.
    """
    path = str(Location.relative(path))
    self.provider.delete(self._uri(path))
    if self._paths is not None and path.casefold() in self._identities:
      del self._paths[self._identities.pop(path.casefold())]

  def path_of(self, obj: DataObject) -> y2path:
    """Where obj belongs in this Container by its naming templates. Callers: Dagster jobs, admin_ui's template preview.

    Args:
      obj (DataObject): Object supplying naming-template context, including its parent when present.

    Returns:
      y2path: Nonempty relative destination path produced by the configured naming templates.
    """
    if self.templates is None:
      raise ValueError('Container requires naming templates to place a DataObject')
    uri = urlsplit(str(obj.uri))
    context = dict(uri=str(obj.uri), endpoint=uri.path, tenant=uri.netloc, inside='.', it=obj.content,
                   unquote=unquote, identity=obj.identity, filename=obj.name, kind=obj.kind)
    if 'date' in self.templates.named:
      value = self.templates.render_template('date', it=obj.content, uri=str(obj.uri),
        parent=obj.parent.content if obj.parent is not None else None)
      context['date'] = datetime.fromisoformat(value) if value else None
    if obj.parent is not None:
      path = self.templates.render_template(obj.kind, object_path=str(self.path_of(obj.parent)),
                                            parent=obj.parent.content, **context)
    else:
      path = self.templates.render_template('filename', **context)
    if not isinstance(path, str) or not path.strip():
      raise ValueError('Object filename template must return a nonempty relative path')
    path = str(Location.relative(path))
    if 'identity' not in self.templates.named:
      return y2path(path)
    context['path'] = path
    identity = self.templates.render_template('identity', **context)
    if identity is None:
      return y2path(path)
    if not isinstance(identity, str) or not identity:
      raise ValueError('Object identity template must return a nonempty string or None')
    paths = self._saved(context)
    if identity in paths:
      return y2path(paths[identity])
    original, number, attempted = path, 1, set()
    while path.casefold() in self._identities:
      if path.casefold() in attempted:
        raise ValueError('Collision template must produce a new path')
      attempted.add(path.casefold())
      number += 1
      path = self.templates.render_template('collision', **(context | {'path': original, 'number': number}))
      if not isinstance(path, str) or not path.strip():
        raise ValueError('Collision template must return a nonempty relative path')
      path = str(Location.relative(path))
    paths[identity] = path
    self._identities[path.casefold()] = identity
    return y2path(path)

  def _saved(self, context: dict[str, Any]) -> dict[str, str]:
    """The saved JSON objects in this Container by identity, read once."""
    if self._paths is None:
      self._paths = {}
      folders = ['']
      while folders:
        for row in self.ls(folders.pop()):
          if row['type'] == 'directory':
            folders.append(row['name'])
            continue
          if not row['name'].endswith('.json'):
            continue
          key = self.templates.render_template('identity', **(context | {
            'it': self.provider.read(self._uri(row['name'])).content, 'path': row['name']}))
          if key is None:
            continue
          if key in self._paths:
            raise ValueError(f"{row['name']}: duplicate saved object identity")
          self._paths[key] = row['name']
          self._identities[row['name'].casefold()] = key
    return self._paths

  @contextmanager
  def refresh(self, state: dict[str, Any], path: y2path | str = '') -> Iterator[Iterator[DataObject]]:
    """The objects changed at or below path since state was recorded, removed ones marked removed.

    state belongs to the caller. It advances only when every change was consumed inside the context and nothing
    raised, so a failed run is read again next time. Caller: Dagster jobs.

    Args:
      state (dict[str, Any]): Caller-owned synchronization state; advanced only after successful full consumption.
      path (y2path | str): Relative starting path; empty selects the Container root.

    Returns:
      Iterator[Iterator[DataObject]]: Context manager yielding changed DataObjects, including removed objects marked removed. The caller must consume the iterator inside the context for state to advance.
    """
    with self.provider.refresh(state, self._uri(path)) as (objects, commit):
      complete = False
      def changes() -> Iterator[DataObject]:
        nonlocal complete
        for obj in objects:
          if not isinstance(obj, DataObject):
            raise TypeError('Container refresh must return DataObjects')
          yield obj
        complete = True
      yield changes()
      if not complete:
        raise RuntimeError('refresh was not fully consumed; source state was not advanced')
      commit()


class Location:
  """One place in the configured hierarchy, known by its uid.

  The top of the hierarchy is configured; below it are Locations its Provider discovers, down to the Containers
  that hold objects. A Location without a Provider only groups the Locations below it.

  Attributes:
    uid (str): Its uid from configuration: alex-laptop-data, github-ran.
    uri (y2uri): Its canonical uri.
    provider (Provider | None): The Provider, with its connection, that reaches it.
    parent (Location | None): The Location above it; None at the top.
  """

  def __init__(self, row: Mapping[str, Any], *, provider: Provider | None = None, parent: 'Location | None' = None,
               children: Callable[[], Iterable['Location']] | None = None,
               templates: Mapping[str, str] | None = None, here: tuple[Provider, y2uri] | None = None) -> None:
    """A Location from its configuration row. children lists the configured Locations below it; templates name
    where DataObjects go in its Container. here is the Provider and uri this host reads it through, its folder on this
    host, when it has one."""
    self.uid = row['uid']
    if not isinstance(self.uid, str) or not self.uid:
      raise ValueError('every Location requires a nonempty uid')
    self._row = deepcopy(dict(row))
    self.uri = y2uri(row['canonical'])
    self.provider = provider
    self.parent = parent
    self.templates = deepcopy(dict(templates)) if templates is not None else None
    self._children = children
    self.here = here

  @property
  def data(self) -> dict[str, Any]:
    """Its configuration row: uid, provider, parent, canonical, name, kind, path, service, icon, tags, folders."""
    return deepcopy(self._row)

  def ls(self) -> list['Location']:
    """The Locations directly below this one: the configured ones, then those its Provider finds.

    Callers: admin_ui, FileIndexer, lake Dagster.

    Returns:
      list[Location]: Direct child Locations, configured first and provider-discovered afterward; each carries uid, uri, parent and its configuration data.
    """
    children = list(self._children()) if self._children is not None else []
    if self.provider is None:
      return children
    configured = {child.uri for child in children}
    for path, name in self.provider.locations(self.uri):
      uri = self.provider.join(self.uri, path)
      if uri in configured:
        continue
      children.append(Location(self._row | {'uid': f"{self.uid.rstrip('/')}/{path}", 'canonical': str(uri),
        'name': name, 'path': unquote(urlsplit(str(uri)).path.lstrip('/')), 'parent': self.uid},
        provider=self.provider, parent=self, templates=self.templates))
    return children

  def walk(self) -> Iterator[tuple['Location', list['Location']]]:
    """This Location and every Location below it, each with the Locations directly below it.

    Returns:
      Iterator[tuple[Location, list[Location]]]: Depth-first pairs of a Location and its immediate children, starting with this Location.
    """
    children = self.ls()
    yield self, children
    for child in children:
      yield from child.walk()

  def container(self, path: y2path | str = '') -> Container:
    """The Container at path below this Location. Callers: FileIndexer, Dagster jobs.

    Args:
      path (y2path | str): Relative path below this Location; empty selects its root.

    Returns:
      Container: Container bound to the Location's folder on this host when it has one, else to its Provider and canonical URI,
        with its naming templates. A Location without a Provider raises ValueError.
    """
    provider, uri = self.here or (self.provider, self.uri)
    if provider is None:
      raise ValueError(f'{self.uid}: no Provider reaches this Location')
    return Container(provider, provider.join(uri, self.relative(path)), templates=self.templates)

  def uri_of(self, path: y2path | str = '') -> y2uri:
    """The canonical uri of path below this Location, each name uri-escaped. Caller: FileIndexer.

    Args:
      path (y2path | str): Relative path below this Location; empty selects its root.

    Returns:
      y2uri: Canonical URI with each path segment escaped.
    """
    return _join(self.uri, self.relative(path))

  @staticmethod
  def relative(path: y2path | str) -> y2path:
    """path, checked to be relative and slash-separated, with no drive, empty or traversal segment.

    Args:
      path (y2path | str): Relative path; the empty string identifies a root.

    Returns:
      y2path: Validated relative path. Invalid paths raise ValueError.
    """
    if isinstance(path, y2path):
      path = str(path)
    if not isinstance(path, str) or path.startswith('/') or '\\' in path or '://' in path or PureWindowsPath(path).drive:
      raise ValueError('Location path must be relative and slash-separated')
    if path and any(part in ('', '.', '..') for part in path.split('/')):
      raise ValueError('Location path cannot contain empty or traversal segments')
    return y2path(path)


class FileSystem(Provider):
  """Files on this host or on a share it reaches, read through the handlers.

  A file uri names its host and path: file:///D:/Dev on this host, file://alex-pc/D:/Dev by host name. The
  handlers say what each file is; FileSystem is their Provider.
  """
  scheme = 'file'

  def local(self, uri: y2uri | str) -> Path:
    """The path on this host that uri names."""
    parsed = urlsplit(str(uri))
    if parsed.scheme != self.scheme:
      raise ValueError(f'{uri}: FileSystem reaches file uris')
    if parsed.query or parsed.fragment:
      raise ValueError(f'{uri}: a file uri has no query or fragment')
    path = unquote(parsed.path)
    if not path:
      raise ValueError(f'{uri}: select a child Location with a filesystem root')
    if any(part in ('.', '..') for part in path.split('/')):
      raise ValueError(f'{uri}: a file uri cannot contain traversal segments')
    if len(path) >= 3 and path[0] == '/' and path[2] == ':':
      path = path[1:]
    if parsed.netloc and parsed.netloc.casefold() != socket.gethostname().split('.')[0].casefold():
      if os.name == 'nt' and not PureWindowsPath(path).drive:
        return Path('//' + parsed.netloc + path)
      raise ValueError(f'{uri}: file uri refers to another host')
    if len(path) == 2 and path[1] == ':':
      path += '/'
    local = Path(path)
    if not local.is_absolute():
      raise ValueError(f'{uri}: a file uri requires an absolute path')
    return local

  def ls(self, uri: y2uri) -> list[dict[str, Any]]:
    rows = []
    for target in sorted(self.local(uri).iterdir()):
      if target.is_symlink() or target.is_junction():
        # A link is listed as itself, never followed: fsspec's islink and destination.
        rows.append({'name': target.name, 'type': 'other', 'size': target.lstat().st_size, 'islink': True,
                     'destination': os.readlink(target)})
        continue
      rows.append({'name': target.name, 'type': 'directory' if target.is_dir() else 'file',
                   'size': 0 if target.is_dir() else target.stat().st_size})
    return rows

  def info(self, uri: y2uri) -> dict[str, Any]:
    """The record of the path at uri, as probe gives it from its stat and its name; nothing is read."""
    return handlers.probe(self.local(uri))

  def open(self, uri: y2uri, mode: str = 'rb') -> BinaryIO:
    if mode not in ('rb', 'r'):
      raise ValueError('open reads; store objects with write')
    return self.local(uri).open(mode)

  def read(self, uri: y2uri) -> DataObject:
    """The file at uri: a JSON file's parsed value, any other file's byte stream."""
    target = self.local(uri)
    content = json.loads(target.read_bytes()) if target.suffix.casefold() == '.json' else target.open('rb')
    return DataObject(uri, content, None, name=target.name)

  def write(self, uri: y2uri, obj: DataObject, *, replace: bool | Callable[[], bool] = False) -> None:
    """Store obj.content at uri: JSON values as UTF-8 JSON, bytes and streams unchanged.

    The file is staged beside its destination and moved into place. A held file that matches is left alone: JSON
    by its value, anything else by its bytes. A held file the new bytes strictly extend is replaced, as an
    append-only file grows. Any other held file is replaced only by replace, true or returning true when called,
    and raises FileExistsError otherwise.
    """
    target = self.local(uri)
    target.parent.mkdir(parents=True, exist_ok=True)
    incoming = obj.content
    binary = isinstance(incoming, bytes) or hasattr(incoming, 'read')
    if not binary:
      stream = BytesIO((json.dumps(incoming, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8'))
    elif isinstance(incoming, bytes):
      stream = BytesIO(incoming)
    else:
      stream = incoming
    if isinstance(stream, BytesIO) and target.is_file() and target.read_bytes() == stream.getvalue():
      return
    # Stage beside the object so replacement stays on its filesystem.
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.', suffix='.pending', delete=False) as staged:
      pending = Path(staged.name)
      try:
        shutil.copyfileobj(stream, staged)
        staged.flush()
        os.fsync(staged.fileno())
      except BaseException:
        staged.close()
        pending.unlink()
        raise
    try:
      try:
        os.link(pending, target)
        return
      except FileExistsError:
        pass
      if filecmp.cmp(pending, target, shallow=False):
        return
      if not binary and json.loads(target.read_bytes()) == incoming:
        return
      if not _extends(pending, target) and not (replace() if callable(replace) else replace):
        raise FileExistsError(f'{target}: holds different content; a rule in its folder decides whether it is replaced')
      os.replace(pending, target)
    finally:
      pending.unlink(missing_ok=True)

  def delete(self, uri: y2uri) -> None:
    self.local(uri).unlink()

  def walk(self, uri: y2uri, path: y2path | str = '', *, level: str = 'files', recursive: bool = False,
           boundaries: Iterable[y2path | str] = ()) -> Iterator[tuple[dict, list[dict]]]:
    yield from walk_files(self.local(uri), str(Location.relative(path)), level, recursive, boundaries)

  @contextmanager
  def refresh(self, state: dict[str, Any], uri: y2uri) -> Iterator[tuple[Iterator[DataObject], Callable[[], None]]]:
    """Files changed at or below uri since state was recorded, by modification time and size.

    state is keyed by the local file uri of the refreshed path; each object's identity is its path below uri.
    """
    root = self.local(uri).resolve()
    base = root if root.is_dir() else root.parent
    scope = root.as_uri()
    previous = state[scope] if scope in state else {}
    pending: dict[str, list[int]] = {}

    def objects() -> Iterator[DataObject]:
      targets = root.rglob('*') if root.is_dir() else [root]
      for target in targets:
        if target.is_dir() or target.suffix == '.pending':
          continue
        name = target.relative_to(base).as_posix()
        stat = target.stat()
        signature = [stat.st_mtime_ns, stat.st_size]
        if name not in previous or previous[name] != signature:
          obj = replace(self.read(_join(uri, name) if root.is_dir() else y2uri(uri)), identity=name)
          try:
            yield obj
          finally:
            if hasattr(obj.content, 'close'):
              obj.content.close()
        pending[name] = signature
      for name in previous.keys() - pending.keys():
        yield DataObject(_join(uri, name) if root.is_dir() else y2uri(uri), b'', name, name=PurePosixPath(name).name, removed=True)

    def commit() -> None:
      state[scope] = pending

    yield objects(), commit


def _extends(new: Path, held: Path) -> bool:
  """Whether new is strictly larger than held and begins with every byte of it."""
  size = held.stat().st_size
  if new.stat().st_size <= size:
    return False
  with new.open('rb') as longer, held.open('rb') as shorter:
    while chunk := shorter.read(1 << 20):
      if longer.read(len(chunk)) != chunk:
        return False
  return True


def _updated(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
  result = deepcopy(previous)
  for key, value in incoming.items():
    if key in result and isinstance(result[key], dict) and isinstance(value, dict):
      result[key] = _updated(result[key], value)
    else:
      result[key] = deepcopy(value)
  return result

# endregion
# region names

# A name this host cannot spell is spelled with these replaced, and no longer than NAME_LIMIT.
UNSAFE = '\\/:*?"<>|\r\n\t'
NAME_LIMIT = 254


def _display_order(path: Path) -> tuple[bool, str]:
    """Sort folders before files, then names without case sensitivity."""

    return not (path.is_dir() and not path.is_symlink()), path.name.casefold()


def _metadata_text(value: Any) -> str | list[datetime]:
    """JSON text for a value the index carries: a time in this host's local zone, anything else as written."""
    if isinstance(value, TimeSpan):
        return [value.start, value.end]
    if isinstance(value, datetime):
        return str(value.astimezone())
    return str(value)


class _RarFileSystem(AbstractArchiveFileSystem):
  """A RAR archive through fsspec's archive interface, read by the installed RARLAB rar or unrar: listed from its
  technical listing, and a member extracted alone when it is opened, the one before it removed. An archive on this
  host is read in place. A password-protected or unreadable archive raises."""

  protocol = 'gppu-rar'
  cachable = False
  timeout = 1800   # one RAR gets half an hour of the command; a longer one is an error, not a partial extraction

  def __init__(self, fo: str, target_protocol=None, target_options=None, **kwargs):
    super().__init__(**kwargs)
    self._scratch = _scratch('gppufs-rar-')
    if target_protocol in (None, 'file', 'local') and Path(fo).is_file():
      self._archive = Path(fo)   # on this host, a mounted share's among it: read where it is, never copied
    else:
      self._archive = Path(self._scratch.name) / 'archive.rar'
      options = {} if target_options is None else target_options
      with open_uri(fo, protocol=target_protocol, **options) as source, self._archive.open('wb') as target:
        shutil.copyfileobj(source, target)
    self.dir_cache = self._listing()
    self._member: Path | None = None

  @staticmethod
  def executable() -> Path:
    """The RARLAB command: rar or unrar on PATH, else, on Windows, WinRAR's own folder, which its installer does not
    put on PATH. Its absence raises."""
    for command in ('rar', 'unrar'):
      if found := shutil.which(command):
        return full_path(found)
    if detect_os() == OSType.W11:
      for name in ('Rar.exe', 'UnRAR.exe'):
        for root in ('ProgramFiles', 'ProgramFiles(x86)'):
          if root in os.environ and (candidate := Path(os.environ[root]) / 'WinRAR' / name).is_file():
            return full_path(candidate)
    raise FileNotFoundError('RARLAB rar or unrar is required to read RAR archives')

  def _listing(self) -> dict[str, dict]:
    """Every member, and every folder above one the listing does not name, as fsspec's archive entries."""
    completed = subprocess.run([str(self.executable()), 'lt', '-c-', '-p-', '-scf', '-y', str(self._archive)],
                               stdin=subprocess.DEVNULL, capture_output=True, check=False)
    output = completed.stdout.decode('utf-8')
    if completed.returncode:
      raise ValueError(f'RAR command exited with {completed.returncode}: '
                       f"{completed.stderr.decode('utf-8').strip() or output.strip()}")
    entries: list[dict[str, str]] = []
    for line in output.splitlines():
      if (field := re.match(r'^\s*([^:]+):\s?(.*)$', line)) is None:
        continue
      key, value = (part.strip() for part in field.groups())
      if key == 'Name':
        entries.append({})
      if entries:
        entries[-1][key] = value
    listing: dict[str, dict] = {}
    self._names: dict[str, str] = {}   # a member's path, as fsspec names it, to the name the archive gives it
    for entry in entries:
      name = PurePosixPath(entry['Name'].lstrip('/').replace('\\', '/'))
      self._names[name.as_posix()] = entry['Name']
      if name.is_absolute() or '..' in name.parts or (name.parts and name.parts[0].endswith(':')):
        raise ValueError(f"unsafe path inside archive: {entry['Name']}")
      folder = entry['Type'] == 'Directory'
      modified = next((value for key, value in entry.items() if key.casefold() in ('modified', 'mtime')), None)
      listing[name.as_posix()] = {'name': name.as_posix(), 'type': 'directory' if folder else 'file',
                                  'size': 0 if folder else int(entry['Size']),
                                  'mtime': modified and handlers.Handler.valid_time(datetime.fromisoformat(modified).astimezone())}
      for parent in name.parents:
        if parent != PurePosixPath('.'):
          listing.setdefault(parent.as_posix(), {'name': parent.as_posix(), 'type': 'directory', 'size': 0, 'mtime': None})
    return listing

  def _get_dirs(self):
    return self.dir_cache

  def _open(self, path, mode='rb', **kwargs):
    if mode != 'rb':
      raise NotImplementedError('RAR listings are read-only')
    if self._member is not None:
      shutil.rmtree(self._member, ignore_errors=True)   # the member opened before; what was read of it is the caller's
    self._member = Path(tempfile.mkdtemp(dir=self._scratch.name))
    subprocess.run([str(self.executable()), 'x', '-y', '-inul', '-p-', str(self._archive), self._names[PurePosixPath(path).as_posix()],
                    str(self._member) + os.sep], stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=self.timeout)
    return (self._member / PurePosixPath(path)).open('rb')

  def close(self):
    self._scratch.cleanup()


register_implementation('gppu-rar', _RarFileSystem)


# Where gppufs and the walk put what they must hold for a moment: the cache, never the system's temporary folder.
CACHE = Path('C:/.cache') if os.name == 'nt' else Path.home() / '.cache'

def _scratch(prefix: str) -> tempfile.TemporaryDirectory:
  CACHE.mkdir(parents=True, exist_ok=True)
  return tempfile.TemporaryDirectory(prefix=prefix, dir=CACHE)


def _probe_name(name: str, directory: bool, size: int | None = None) -> handlers.Record:
  """What probe says of an entry known only by its name, whether it is a folder and its size, from a stand-in of it that
  is gone when probe has answered; nothing of the entry is read."""
  spelled = ''.join('_' if letter in UNSAFE else letter for letter in name).rstrip(' .') or 'entry'
  if len(spelled) > NAME_LIMIT:
    stem, dot, suffix = spelled.rpartition('.')
    spelled = spelled[:NAME_LIMIT - len(suffix) - 1] + dot + suffix if dot else spelled[:NAME_LIMIT]
  with _scratch('gppufs-name-') as scratch:
    stand_in = Path(scratch) / spelled
    stand_in.mkdir() if directory else stand_in.write_bytes(b'\0' if size else b'')   # probe names a handler only for a file that holds something
    record = handlers.probe(stand_in)
  if not directory:
    record.meta['size'] = int(size or 0)
  return record


def _modified(native: dict) -> datetime | None:
  """The time a listing gives an entry, as a time valid_time takes."""
  if 'mtime' in native:
    value = native['mtime']
    if isinstance(value, (float, int)):
      return handlers.Handler.valid_time(datetime.fromtimestamp(value, timezone.utc))
    if isinstance(value, datetime):
      return handlers.Handler.valid_time(value)
    if isinstance(value, str):
      return handlers.Handler.valid_time(datetime.fromisoformat(value.replace('Z', '+00:00')))
  if 'date_time' in native:
    return handlers.Handler.valid_time(datetime(*native['date_time']).astimezone())
  return None


# endregion
# region indexing

LEVELS = ('refresh', 'files', 'handlers', 'archives')
FOLDER_CLASSES = {'.git': '.git', '.svn': '.git', '__pycache__': 'py_cache',
  '.venv': 'py_cache', 'venv': 'py_cache', 'node_modules': 'npm_cache',
  '.idea': 'ide_config', '.vscode': 'ide_config'}


def _selection(path, level, boundaries):
  Location.relative(path)
  if level not in LEVELS:
    raise ValueError(f'unknown indexing level: {level}')
  return {str(Location.relative(value)) for value in boundaries}


def walk_container(container, path, level, recursive, boundaries):
  """The same enumeration contract for non-filesystem Containers."""
  boundaries = _selection(path, level, boundaries)

  def visit(folder):
    rows = []
    for item in container.ls(folder):
      row = dict(item)
      name = str(Location.relative(row['name']))
      if name.rpartition('/')[0] != folder or name == folder:
        raise ValueError(f'{name}: listing must contain immediate Container children')
      if row['type'] != 'directory' and level == 'refresh':
        continue
      if name in boundaries:
        row['boundary'] = 'Location'
      elif row['type'] != 'directory' and level in ('handlers', 'archives'):
        obj = container.read(name)
        try:
          row['object'] = {'uri': str(obj.uri), 'identity': obj.identity, 'kind': obj.kind}
        finally:
          if hasattr(obj.content, 'close'):
            obj.content.close()
      rows.append(row)
    yield {'name': folder, 'type': 'directory', 'size': 0}, rows
    if recursive:
      for row in rows:
        if row['type'] == 'directory' and row['name'] not in boundaries:
          yield from visit(row['name'])
  yield from visit(path)


def _walked(name: str, kind: str, size: int | None, modified: datetime | None, record: handlers.Record,
            unread: str | None = None) -> dict:
  """One row of a walk: the entry's name below the walked folder, its type and size as listed, and the record its
  handler read; a session is fingerprinted by its harness and uid."""
  row = {'name': name, 'type': kind, 'size': size, 'modified_at': modified,
         'handlers': [record.type], 'record': vars(record)}
  if name.casefold().endswith(handlers.ARCHIVES):
    row['handlers'].append('archive')
  if isinstance(record, handlers.Session) and record.uid:
    row['fingerprints'] = [('session', f'{record.type}/{record.uid}')]
  elif record.type == handlers.SessionFolderHandler.type and record.data.get('uid'):
    row['fingerprints'] = [('session', f"{record.data['harness']}/{record.data['uid']}")]
  if 'target' in record.data:
    row['target'] = record.data['target']
  if unread is not None:
    row['unread'] = [unread]
  return row


def _read(path: Path, parse: bool) -> tuple[handlers.Record, str | None]:
  """What probe gives of path, read by its handler when parse is asked; a read that fails is said, not raised, so
  the walk goes on."""
  record = handlers.probe(path)
  handler = handlers.HANDLERS.get(record.type)
  if not parse or handler is None or issubclass(handler, handlers.FolderHandler):
    return record, None
  try:
    return handler.parse(path), None
  except Exception as error:   # the walk records what it could not read and goes on
    return record, f'{handler.__name__}: {type(error).__name__}: {error}'


@contextmanager
def _archive(path: Path) -> Iterator[AbstractFileSystem]:
  """The fsspec file system of an archive on this host, as gppufs opens one, the archive closed when it is done."""
  name = path.name.casefold()
  if name.endswith('.rar'):
    archive = _RarFileSystem(str(path))
    try:
      yield archive
    finally:
      archive.close()
    return
  with path.open('rb') as handle:
    if name.endswith('.zip'):
      from fsspec.implementations.zip import ZipFileSystem
      archive = ZipFileSystem(fo=handle, skip_instance_cache=True)
    else:
      from fsspec.implementations.tar import TarFileSystem
      archive = TarFileSystem(fo=handle, compression='gzip', skip_instance_cache=True)
    try:
      yield archive
    finally:
      archive.close()


def walk_files(root: Path, path: str, level: str, recursive: bool,
               boundaries: Iterable[str]) -> Iterator[tuple[dict, list[dict]]]:
  """FileIndexer's walk of a folder on this host: each folder and the rows of what it holds, probed, and from level
  `handlers` read by their handlers; from level `archives` an archive's members too, read from copies through
  gppufs's archive drivers. `refresh` lists folders only. A link, a Location below and a folder of FOLDER_CLASSES or
  ignored are boundaries, not entered; an ignored file is not listed."""
  boundaries = _selection(path, level, boundaries)
  parse = level in ('handlers', 'archives')

  def members(fs, under: str) -> Iterator[tuple[dict, list[dict]]]:
    """An archive's members, listed once with no bytes read and identified by probe of their names; a member a
    handler reads is fetched alone into the cache when the walk reaches it, read and removed, and a nested archive
    is held only while it is walked."""
    listing = {item['name'].rstrip('/'): item for item in fs.find('', withdirs=True, detail=True).values()}
    identified = {member: _probe_name(PurePosixPath(member).name, item['type'] == 'directory', item.get('size'))
                  for member, item in listing.items()}

    def wanted(member: str) -> bool:
      record = identified[member]
      return listing[member]['type'] != 'directory' and (member.casefold().endswith(handlers.ARCHIVES)
        or handlers.HANDLERS.get(record.type) not in (None, handlers.FileHandler))

    def folder(prefix: str, under: str) -> Iterator[tuple[dict, list[dict]]]:
      rows, descend, nested = [], [], []
      children = [member for member in listing if PurePosixPath(member).parent.as_posix() == (prefix or '.')]
      for member in sorted(children, key=lambda member: (listing[member]['type'] != 'directory', member.casefold())):
        item, record, unread = listing[member], identified[member], None
        name = f"{under}/{PurePosixPath(member).name}"
        kind = 'directory' if item['type'] == 'directory' else 'file'
        if kind == 'file' and (level == 'refresh' or record.type == 'ignored'):
          continue
        archive = kind == 'file' and member.casefold().endswith(handlers.ARCHIVES)
        if wanted(member) and not archive:
          with _scratch('container-index-') as scratch:
            copy = Path(scratch) / PurePosixPath(member).name
            try:
              fs.get_file(member, str(copy))
            except Exception as error:   # a member that cannot be extracted is said, and the walk goes on
              unread = f'extract: {type(error).__name__}: {error}'
            else:
              record, unread = _read(copy, parse)
        row = _walked(name, kind, item.get('size'), _modified(item), record, unread)
        if kind == 'directory':
          if PurePosixPath(member).name in FOLDER_CLASSES or record.type == 'ignored':
            row['boundary'] = FOLDER_CLASSES.get(PurePosixPath(member).name, 'Ignored')
          elif recursive:
            descend.append((member, name))
        elif archive:
          nested.append((member, name, row))
        rows.append(row)
      found = []
      for member, name, row in nested:   # read whole before this folder is answered, held only while it is read
        with _scratch('container-index-') as scratch:
          copy = Path(scratch) / PurePosixPath(member).name
          try:
            fs.get_file(member, str(copy))
            with _archive(copy) as inner:
              found.append(list(members(inner, name)))
          except Exception as error:   # an archive read failure remains file evidence, never a successful enumeration
            row['unread'] = [*row.get('unread', []), f'archive: {type(error).__name__}: {error}']
      yield {'name': under, 'type': 'directory', 'size': 0}, rows
      for listing_below in found:
        yield from listing_below
      for member, name in descend:
        yield from folder(member, name)

    yield from folder('', under)

  def visit(folder: Path, under: str) -> Iterator[tuple[dict, list[dict]]]:
    try:
      entries = sorted(folder.iterdir(), key=_display_order)
    except OSError as error:
      raise OSError(f'{under}: directory enumeration failed: {type(error).__name__}: {error}') from error
    rows, descend, archives = [], [], []
    for entry in entries:
      name = f'{under}/{entry.name}' if under else entry.name
      record, unread = _read(entry, parse)
      folder_like = record.type in handlers.FOLDERS
      if record.type == 'ignored' and not entry.is_dir():
        continue
      if level == 'refresh' and not (folder_like or entry.is_dir()):
        continue
      stat = entry.lstat()
      row = _walked(name, 'directory' if entry.is_dir() else 'file', None if entry.is_dir() else stat.st_size,
                    handlers.Handler.valid_time(datetime.fromtimestamp(stat.st_mtime).astimezone()), record, unread)
      if record.type in ('symlink', 'junction'):
        row['boundary'] = 'link'
        row['target'] = str(entry.resolve())
      elif name in boundaries:
        row['boundary'] = 'Location'
      elif entry.is_dir():
        if entry.name in FOLDER_CLASSES or record.type == 'ignored':
          row['boundary'] = FOLDER_CLASSES.get(entry.name, 'Ignored')
        elif recursive:
          descend.append((entry, name))
      elif level == 'archives' and 'archive' in row['handlers']:
        archives.append((entry, name, row))
      rows.append(row)
    found = []
    for entry, name, row in archives:   # read whole before this folder is answered
      try:
        with _archive(entry) as archive:
          found.append(list(members(archive, name)))
      except Exception as error:   # an archive read failure remains file evidence, never a successful enumeration
        row['unread'] = [*row.get('unread', []), f'archive: {type(error).__name__}: {error}']
    yield {'name': under, 'type': 'directory', 'size': 0}, rows
    for listing_below in found:
      yield from listing_below
    for entry, name in descend:
      yield from visit(entry, name)

  selected = root / path
  if not selected.exists():
    raise NotADirectoryError(str(selected))
  record = handlers.probe(selected)
  if record.type in ('symlink', 'junction'):
    raise PermissionError(f'{path}: a link cannot be selected for traversal')
  if record.type == 'ignored':
    raise PermissionError(f'{path}: selected directory is excluded by the ignore rules')
  if not record.type in handlers.FOLDERS:
    raise NotADirectoryError(str(selected))
  yield from visit(selected, path)

# endregion
