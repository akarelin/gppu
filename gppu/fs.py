r"""gppufs: DataObjects in Containers, Containers in Locations.

A Location is one place in the configured hierarchy, known by its uid. A Container holds alike objects and takes
paths relative to itself. A Provider reaches objects by uri over one connection, and an instance of it is that Connection:
FileSystem is the Provider of files, and M365, Telegram and Plaud are Providers in CRAP. A DataObject is content
with its uri.

The public methods are the API. The Lake, which saves objects and retrieves them by uri, is gppu.lake.

Handlers:
Typed, caller-composed handlers for large file hierarchies.

A domain handler receives one :class:`pathlib.Path` and returns ``(stats,
typed_object)``. Statistics are derived from the complete typed object. Users
select behavior with normal multiple inheritance::

    class MyFiles(
        FileHandler,
        IgnoredHandler,
        MarkdownHandler,
        CSVHandler,
        LogHandler,
        FolderHandler,
    ):
        pass

    files = MyFiles(metadata={"source": "local"})

``GppuFileSystem(location)`` composes the implemented parsers behind fsspec
``ls`` and ``info``, with SQLite metadata indexes beside the source folders.

Every handler copies the optional metadata mapping supplied by its caller.
``Probe.metadata`` combines that mapping with metadata detected by the typed
object. Caller metadata wins when the same key exists in both mappings.

Default calls do not stop a hierarchy scan. A read failure is represented by
:class:`HandlerError`; a composed probe stores it on ``Probe.error`` and
``Record.errors``. Construct a handler with ``strict=True`` when an exception
and traceback are required. Cancellation and process-exit exceptions are not
captured.

Public I/O calls decorated with :func:`gppu.sync` return directly outside an
event loop and are awaitable inside one. Their ``*_sync`` methods are the
strict worker implementations. All local paths are resolved by
:func:`gppu.full_path`.

Archive members use the same :class:`Record` hierarchy as filesystem entries,
with the archive path in ``location``. Ignored folders remain visible but are
not descended into. ``GitHandler`` reads only local history and configuration;
it never fetches or contacts an upstream.
"""
from __future__ import annotations

import filecmp
import importlib
import io
import json
import os
import posixpath
import re
import shutil
import socket
import sqlite3
import subprocess
import time
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, Protocol, runtime_checkable
from urllib.parse import quote, unquote, urlsplit
from threading import RLock

import yaml
from fsspec import open as open_uri, register_implementation
from fsspec.archive import AbstractArchiveFileSystem
from fsspec.core import url_to_fs
from fsspec.implementations.local import LocalFileSystem
from fsspec.spec import AbstractFileSystem
from fsspec.utils import stringify_path

from .gppu import TimeSpan, OSType, TemplateSet, detect_os, full_path, sync, y2path, y2uri
from .gppu import Env, Warn
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
               templates: Mapping[str, str] | None = None) -> None:
    """A Location from its configuration row. children lists the configured Locations below it; templates name
    where DataObjects go in its Container."""
    self.uid = row['uid']
    if not isinstance(self.uid, str) or not self.uid:
      raise ValueError('every Location requires a nonempty uid')
    self._row = deepcopy(dict(row))
    self.uri = y2uri(row['canonical'])
    self.provider = provider
    self.parent = parent
    self.templates = deepcopy(dict(templates)) if templates is not None else None
    self._children = children

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
      Container: Container bound to the Location Provider, canonical URI and naming templates. A Location without a Provider raises ValueError.
    """
    if self.provider is None:
      raise ValueError(f'{self.uid}: no Provider reaches this Location')
    return Container(self.provider, self.provider.join(self.uri, self.relative(path)), templates=self.templates)

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


@runtime_checkable
class GppuIndex(Protocol):
  """Where the metadata of a location's entries is kept when it is kept somewhere other than beside it.

  Alex, 2026-09-17 03:45: "handler in my view was a thing that gets metadata for any locations
  (recursively) / If metadata is already in database - handler is not involved". So a filesystem given
  an index asks it first and runs a handler only for what it does not hold, and hands back what the
  handler read so the next lookup does not run it again.

  An entry is named by its address — the uri gppufs puts on every row, and the permalink of a
  configured location where there is one. An implementation may accept an entity's uid as well; gppufs
  only ever asks with an address. Nothing here knows what the index is made of: the implementation
  that keeps Alex's index in Postgres lives with the indexer, in CRAP, and gppu imports none of it.
  """

  def entry(self, address: str) -> tuple[dict, list[dict] | None] | None:
    """One entry's metadata and the listing of what is in it, or None when the index holds neither.

    The listing is None for a thing that is not a container, and for a container the index has not
    been told the contents of. Both come back in the same shape gppufs stores: the metadata is the
    row, and each child of the listing carries `path`, `type` and `ino`.
    """

  def put(self, entries: Mapping[str, tuple[dict | None, list[dict] | None]]) -> None:
    """Keep what the handlers read, by address. A None stands for a part this call does not change."""

  def moved(self, source: str, destination: str) -> None:
    """The entry at `source`, and everything under it, is at `destination` now.

    What the index holds of a thing moves with the thing. Alex's reason for a file manager built on
    this filesystem is that moving a folder between two indexed places keeps the index: the rows are
    carried over, never thrown away and read again, so what was said about a file survives the move.

    Every address the index holds of what moved is rewritten, the entries' own and the addresses
    inside them, because an entry that still names where it was is an entry that cannot be read.
    """


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


class GppuFileSystem(AbstractFileSystem):
  """fsspec listings enriched by handlers and stored beside their location.

  ``location`` is the only required setting: an absolute path or a URL, never
  the folder the caller happens to be in. Its index is
  ``location/.<location-name>.gppufs.sqlite``. An existing index named for
  a descendant folder owns that subtree. Index rows use relative addresses
  so moving a folder with its database preserves its listings.

  ``ls`` and ``info`` return the same metadata dictionaries from SQLite or
  live parsing. ``refresh=True`` requests live data. An absent cached row
  is populated by a live read; a failed read never substitutes stale data.
  Every time in the metadata is written in this host's local zone.
  Index files and SQLite journal companions are excluded from listings
  and aggregates. The example applications do no parsing or persistence.

  Archives use the same URI scheme and path format as their location.
  Appending ``/outer.zip/inner.zip/note.md`` addresses a nested member;
  its parent is ``/outer.zip/inner.zip``. An archive's file metadata and
  member listing share its ordinary URI. Archive drivers are internal.

  ``cat_file``, ``open``, ``head``, ``pipe_file`` and the rest of the fsspec
  surface read and write bytes: a physical file through the base filesystem,
  a member through its archive, and a write to a member is refused. A write
  does not touch the index, so what was identified stands until the folder is
  read again with ``refresh=True``.

  When ``locations`` is given, a location's own address is an address this
  filesystem answers to, so ``info('sd://SD.agents/memory/MEMORY.md')`` reaches
  the entry whose rows carry that address. The deepest configured location
  wins, and an address belonging to a location outside this root is outside it.
  """

  protocol = 'gppu'
  cachable = False
  _index_name = re.compile(r'^\..+\.gppufs\.sqlite(?:-(?:journal|wal|shm))?$')

  def __init__(self, location: str | Path, locations: Mapping[str, Mapping[str, str]] | None = None,
               index: GppuIndex | None = None, **storage_options: Any) -> None:
    if location is None:
      raise ValueError('location is required')
    if '://' not in str(location) and not Path(location).is_absolute():
      raise ValueError(f'{location}: a location is an absolute path or a URL, never a relative one')
    super().__init__()
    self.fs, self.root = url_to_fs(str(location), **storage_options)
    if self.root != '/' and not re.fullmatch(r'[A-Za-z]:/', self.root):
      self.root = self.root.rstrip('/')
    self.location = self.fs.unstrip_protocol(self.root)
    self._lock = RLock()
    self._index = index              # the index that answers first; the file beside the location is a cache
    self._cacheless = False          # set when the store refuses the index it would keep beside itself
    self._memory: dict[str, sqlite3.Connection] = {}   # a remote store's index, held for this instance
    self._indexes: dict[str, str | None] = {}   # folder -> the index it holds, asked of the store once
    self._locations = dict(locations) if locations else {}   # folder -> the location that is there
    self._database_path(self.root)  # Validate the required location name.

  def _location_of(self, path: Path) -> dict[str, str] | None:
    """Which configured location a path on this host is, or is inside: its location, canonical address, the path's
    address and its folder in it, the deepest location containing it winning; None when none does."""
    here = full_path(path).as_posix()
    base = max((folder for folder in self._locations if here == folder or here.startswith(folder.rstrip('/') + '/')),
               key=len, default=None)
    if base is None:
      return None
    row, folder = self._locations[base], '' if here == base else here[len(base.rstrip('/')) + 1:]
    return {'location': str(row['location']), 'canonical': str(row['canonical']),
            'address': _address(str(row['canonical']), folder), 'folder': folder}

  def _database_path(self, folder: str) -> str:
    name = folder.rstrip('/').rsplit('/', 1)[-1].rstrip(':')
    if not name:
      return f'{folder.rstrip("/")}/.gppufs.sqlite'
    return f'{folder.rstrip("/")}/.{name}.gppufs.sqlite'

  def _existing_index(self, folder: str) -> str | None:
    """Whether a folder holds an index of its own, asked of the store once per folder.

    ``_owner`` asks this of every ancestor of every entry, and on a store that is not the local
    filesystem each ask is a round trip. A library of a thousand entries would otherwise spend its
    walk asking SharePoint whether folders hold an index file they have never held. The answer does
    not change under a walk, because gppufs is what creates that file and ``_database`` records it
    here when it does.
    """
    if isinstance(self.fs, LocalFileSystem):
      return self._index_at(folder)     # a local answer costs a stat, and the file can move under us
    if folder not in self._indexes:
      self._indexes[folder] = self._index_at(folder)
    return self._indexes[folder]

  def _index_at(self, folder: str) -> str | None:
    expected = self._database_path(folder)
    if self.fs.isfile(expected) and self.fs.size(expected):   # an empty file is what an open the store refused leaves
      if isinstance(self.fs, LocalFileSystem) and os.name == 'nt':
        actual_name = Path(expected).resolve(strict=True).name
        if actual_name != PurePosixPath(expected).name:
          self.fs.mv(str(PurePosixPath(folder) / actual_name), expected)
      return expected
    if not isinstance(self.fs, LocalFileSystem):
      # Recovering an index that was renamed means renaming it back, which a store gppufs cannot
      # write to will not do. There the index is the file named for the folder or nothing at all:
      # a synced OneDrive carries the index files of the host that syncs it, and those belong to
      # that host's Locations rather than to this one.
      return None
    if not self.fs.isdir(folder):
      return None
    try:
      entries = self.fs.ls(folder, detail=True)
    except PermissionError:
      return None  # A folder this account cannot list holds no index it could read.
    candidates = [item['name'] for item in entries
      if item['type'] == 'file' and item['size'] and item['name'].endswith('.gppufs.sqlite')
      and self._index_name.fullmatch(PurePosixPath(item['name']).name)]
    if not candidates:
      return None
    identity = self.fs.info(folder).get('ino')
    matches = []
    for path in candidates:
      local = isinstance(self.fs, LocalFileSystem)
      uri = Path(path).as_uri() if local else ':memory:'
      if local and Path(path).anchor.startswith('\\\\'):
        uri = uri.replace('file://', 'file:////', 1)  # SQLite requires an empty authority for a UNC path.
      with closing(sqlite3.connect(uri + '?mode=ro' if local else uri, uri=local)) as database:
        if not isinstance(self.fs, LocalFileSystem):
          database.deserialize(self.fs.cat_file(path))
        row = database.execute('SELECT ino FROM gppufs_index').fetchone()
      if row is not None and (identity is None or row[0] == identity):
        matches.append(path)
    if not matches:
      return None  # A copied index belongs to its original folder, not this folder's inode.
    if len(matches) != 1:
      raise ValueError(f'{folder}: cannot identify a unique index after rename')
    self.fs.mv(matches[0], expected)
    return expected

  def _located(self, value: str) -> str:
    """The folder a configured location's own address names, or the value unchanged.

    `LocationHandler` puts `sd://SD.agents/memory/MEMORY.md` on every row it identifies, and that
    address is what the index, the lake and an annotation carry. A filesystem that emits an address
    and then refuses it cannot be asked about what it just said, so a permalink is read here as the
    path it stands for. The deepest configured location wins, the way `located` picks one, and an
    address belonging to a location outside this root still fails as being outside it.
    """
    for folder in sorted(self._locations, key=lambda item: len(str(self._locations[item]['canonical'])), reverse=True):
      rest = _below(str(self._locations[folder]['canonical']), value)
      if rest is not None:
        return posixpath.join(folder, rest) if rest else folder
    return value

  def _key(self, path: str | Path | None) -> str:
    if path is None:
      return '.'
    value = self._located(str(path).replace('\\', '/'))
    if '://' in value:
      value = self.fs._strip_protocol(value)
    if value == self.root or value.rstrip('/') == self.root:
      return '.'
    prefix = self.root.rstrip('/') + '/'
    if value.startswith(prefix):
      value = value[len(prefix):].rstrip('/')
    elif value.startswith('/') or re.match(r'^[A-Za-z]:', value):
      raise ValueError(f'{path}: outside location {self.location}')
    parts = PurePosixPath(value).parts
    if '..' in parts:
      raise ValueError(f'{path}: parent traversal is outside the listing address')
    return PurePosixPath(value).as_posix()

  def _path(self, key: str) -> str:
    return self.root if key == '.' else posixpath.join(self.root, key)

  def _uri(self, key: str) -> str:
    return self.fs.unstrip_protocol(self._path(key))

  def _archive_parent(self, key: str) -> str | None:
    """The physical archive containing this path, if it crosses an archive boundary."""
    for parent in reversed(PurePosixPath(key).parents):
      path = self._path(parent.as_posix())
      if path.casefold().endswith(handlers.ARCHIVES) and self.fs.isfile(path):
        return parent.as_posix()
    return None

  @contextmanager
  def _filesystem(self, key: str, *, container: bool = False):
    """Resolve ordinary container paths; archive filesystem URLs stay inside this access operation."""
    fs, source = self.fs, self.root
    archive_uri = None
    opened = []
    parts = PurePosixPath(key).parts
    try:
      for position, part in enumerate(('', *parts)):
        if part:
          source = posixpath.join(source, part)
        if position == len(parts) and not container:
          break
        if not source.casefold().endswith(handlers.ARCHIVES) or not fs.isfile(source):
          continue
        uri = (fs.unstrip_protocol(source) if archive_uri is None else
               archive_uri.replace('://', '://' + source, 1))
        archive_uri = self._archive_key(uri)
        fs, source = url_to_fs(archive_uri, skip_instance_cache=True)
        opened.append(fs)
      yield fs, source
    finally:
      for archive in reversed(opened):
        archive.close()

  def _parent_key(self, key: str) -> str | None:
    if key == '.':
      return None
    return str(PurePosixPath(key).parent)

  def _owner(self, key: str) -> str:
    if self._cacheless:
      return '.'   # a store that will not hold the file has no folder below the root owning one
    archive = self._archive_parent(key)
    physical = key if archive is None else archive
    folder = PurePosixPath(physical)
    for candidate in (folder, *folder.parents):
      if candidate == PurePosixPath('.'):
        break
      directory = self._path(candidate.as_posix())
      if self._existing_index(directory) is not None:
        return candidate.as_posix()
    return '.'

  @staticmethod
  def _relative(key: str, owner: str) -> str:
    return posixpath.relpath(key, owner)

  @staticmethod
  def _absolute(key: str, owner: str) -> str:
    return posixpath.normpath(str(PurePosixPath(owner) / key))

  def _prepare(self, database: sqlite3.Connection, owner: str, exists: bool) -> None:
    """The two tables an index holds: which folder owns it, and one row per entry."""
    if not exists:
      database.execute('CREATE TABLE IF NOT EXISTS gppufs_index (ino INTEGER)')
      database.execute('INSERT INTO gppufs_index VALUES (?)', (self.fs.info(self._path(owner)).get('ino'),))
    database.execute('CREATE TABLE IF NOT EXISTS gppufs_entries ('
      'path TEXT PRIMARY KEY, metadata TEXT NOT NULL, children TEXT)')

  def _held(self, owner: str) -> sqlite3.Connection:
    """The index held in memory for this instance, read once from the store when the store has one.

    This is the index for a store that is not the local filesystem, and for a folder that will not
    hold the file. An existing index is still read: a folder can be readable and not writable.
    """
    if owner not in self._memory:
      database = sqlite3.connect(':memory:', check_same_thread=False)
      if self._existing_index(self._path(owner)) is not None:
        database.deserialize(self.fs.cat_file(self._database_path(self._path(owner))))
      self._memory[owner] = database
    return self._memory[owner]

  @contextmanager
  def _database(self, owner: str, *, write: bool = False):
    """The location's index: beside the location, or in memory when the store will not hold one.

    Alex, 2026-09-17 03:49: "local databases are caches for runtime and original indexes (often only
    copy because original is a rar file now). / Local dbs are not synced in many cases. Don't count on
    these being present". So this is a cache and never the answer: the index a lookup asks is the one
    in Postgres. A place that refuses the file — GitHub serves read-only, and so does a folder on a
    read-only share — is read through an index this instance keeps in memory instead, and the refusal
    is remembered so the place is asked once rather than once per folder.
    """
    path = self._database_path(self._path(owner))
    if isinstance(self.fs, LocalFileSystem) and not self._cacheless:
      exists = self._existing_index(self._path(owner)) is not None
      if not exists and not write:
        yield None
        return
      try:
        connection = sqlite3.connect(path)
      except sqlite3.OperationalError:   # a read-only folder will not hold the file; only the cache is lost
        self._cacheless = True
      else:
        with closing(connection) as database:
          try:
            database.execute('BEGIN EXCLUSIVE')   # takes the lock a write commits with, which a share may refuse, before anything is written
            database.execute('ROLLBACK')
            if write:
              with database:
                self._prepare(database, owner, exists)   # and the first write, the lock a share refuses
          except sqlite3.OperationalError as error:
            # An SMB share (\s1\Lake on trix) opens the file and refuses its lock: it will not hold the index in place,
            # as a read-only one will not, so it is held in memory and written back whole. Any other refusal is raised.
            if 'database is locked' not in str(error):
              raise
          else:
            with database:
              yield database
            return
        self._cacheless = True
    database = self._held(owner)
    with database:
      if write:
        self._prepare(database, owner, self._columns_of(database))
      elif not self._columns_of(database):
        yield None
        return
      yield database
    if write and not self._cacheless:
      try:
        with self.fs.transaction:
          self.fs.pipe_file(path, database.serialize())
      except (NotImplementedError, OSError):   # the store serves read-only; only the cache file is lost
        self._cacheless = True

  @staticmethod
  def _columns_of(database: sqlite3.Connection) -> bool:
    """Whether this index has been given its tables yet."""
    return bool(database.execute(
      "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gppufs_entries'").fetchone())

  def _stored(self, key: str) -> tuple[dict, list[dict] | None] | None:
    """One entry read back from the location's index: its metadata and its listing, or None.

    The index answers first when there is one, and what it holds is the answer — a handler runs only
    for what it does not hold. The file beside the location is asked after it, and is a cache.

    Not `_cached`: `AbstractFileSystem.__init__` returns early on a truthy `_cached`, so a method of
    that name leaves the instance without `_intrans`, `_transaction` and `dircache`, and every read
    through the fsspec surface raises AttributeError.
    """
    if self._index is not None:
      held = self._index.entry(self._address(key))
      if held is not None and held[0] is not None:
        children = None if held[1] is None else [
          {**child, 'path': self._key(child['path'])} for child in held[1]]
        return self._addressed(key, dict(held[0])), children
    owner = self._owner(key)
    with self._database(owner) as database:
      if database is None:
        return None
      row = database.execute('SELECT metadata, children FROM gppufs_entries WHERE path=?',
        (self._relative(key, owner),)).fetchone()
    if row is None:
      return None
    metadata = json.loads(row[0])
    children = None if row[1] is None else [
      {**child, 'path': self._absolute(child['path'], owner)} for child in json.loads(row[1])]
    return self._addressed(key, metadata), children

  def _address(self, key: str) -> str:
    """How an index names this entry: the permalink a configured location gives it, else its uri.

    An index is shared, and `sd://SD.agents/memory/MEMORY.md` is the one name for that file whichever
    host holds it and whichever checkout asks. A place no configured location covers has only its own
    uri to be named by, and an index keyed on that is an index for this host.
    """
    if self._locations:
      located = self._location_of(Path(self._path(key)))
      if located is not None:
        return located['address']
    return self._uri(key)

  def _for_index(self, key: str, metadata: dict) -> dict:
    """One row as an index is given it: addressed, and every path inside it an address too.

    An index is shared — the same entry is looked up from another host and another checkout — so
    nothing owner-relative and nothing this process only can resolve may go into it.
    """
    value = json.loads(json.dumps(metadata, default=_metadata_text))
    return self._addressed(key, value)

  def _addressed(self, key: str, metadata: dict) -> dict:
    """One stored row with the addresses this filesystem gives it: its own, its name and its parent.

    How a thing is addressed is gppufs's and not the index's, so a row read from the file beside the
    location and a row read from an index given to this filesystem are finished the same way.
    """
    metadata['name'] = self._uri(key)
    metadata['gppu']['path'] = metadata['name']
    metadata['gppu']['name'] = (PurePosixPath(self.root).name if key == '.' else
      PurePosixPath(key).name)
    parent = self._parent_key(key)
    metadata['gppu']['parent'] = self._uri(parent) if parent is not None else None
    return metadata

  def _save(self, rows: dict[str, tuple[dict, list[str] | None]], scope: str, *, in_archive: bool = False) -> None:
    def metadata_for(key):
      if key in rows:
        return rows[key][0]
      cached = self._stored(key)
      if cached is None:
        raise FileNotFoundError(self._uri(key))
      return cached[0]

    # Keep ancestor totals consistent with the refreshed subtree and cached siblings.
    # Archive members do not change their physical archive's byte count.
    if not in_archive:
      child = scope
      for parent in PurePosixPath(scope).parents:
        key = parent.as_posix()
        cached = self._stored(key)
        if cached is None or cached[1] is None:
          break
        metadata, members = cached
        children = list(dict.fromkeys([*(item['path'] for item in members), child]))
        children.sort(key=lambda item: (metadata_for(item)['type'] != 'directory', item.casefold()))
        metadata['gppu'].update(json.loads(json.dumps(
          self._totals(metadata['gppu'], [metadata_for(item) for item in children]), default=_metadata_text)))
        del metadata['gppu']['name'], metadata['gppu']['parent']
        rows[key] = metadata, children
        child = key

    grouped: dict[str, list[tuple]] = {}
    keep: dict[str, tuple[dict | None, list[dict] | None]] = {}
    for key, (metadata, children) in rows.items():
      owner = self._owner(key)
      if owner not in grouped:
        grouped[owner] = []
      listing = None if children is None else [
        {'path': child, 'type': (item := metadata_for(child))['type'], 'ino': item.get('ino')}
        for child in children]
      # What the handlers read goes to the index as well, addressed as this filesystem addresses it.
      # A probe arrives here and not through `_store`, so an index told only by `_store` would answer
      # with the identified row for ever and the probe would run again on every lookup.
      if self._index is not None:
        keep[self._address(key)] = (self._for_index(key, metadata),
          None if listing is None else [{**child, 'path': self._address(child['path'])} for child in listing])
      value = json.loads(json.dumps(metadata, default=_metadata_text))
      value['name'] = self._relative(key, owner)
      value['gppu']['path'] = value['name']
      grouped[owner].append((self._relative(key, owner), json.dumps(value, default=_metadata_text),
        None if listing is None else json.dumps([
          {**child, 'path': self._relative(child['path'], owner)} for child in listing])))
    if keep:
      self._index.put(keep)
    # Publish descendant databases before the listing which references them.
    for owner in sorted(grouped, key=lambda item: len(PurePosixPath(item).parts), reverse=True):
      with self._database(owner, write=True) as database:
        if scope == '.' or owner == scope or owner.startswith(scope + '/'):
          database.execute('DELETE FROM gppufs_entries')
        else:
          relative = self._relative(scope, owner)
          database.execute('DELETE FROM gppufs_entries WHERE path=? OR substr(path,1,?)=?',
            (relative, len(relative) + 1, relative + '/'))
        database.executemany('INSERT INTO gppufs_entries VALUES (?, ?, ?) '
          'ON CONFLICT(path) DO UPDATE SET metadata=excluded.metadata, children=excluded.children', grouped[owner])

  @staticmethod
  def _renamed_key(key: str, old: str, new: str) -> str:
    return new + key[len(old):] if key == old or key.startswith(old + '/') else key

  def _folder_renames(self, key: str, children: list[dict]) -> bool:
    if self._archive_parent(key) is not None:
      return False
    folders = [child for child in children if child['type'] == 'directory' and child['ino'] is not None]
    if not folders:
      return False
    listed = [row for row in self.fs.ls(self._path(key), detail=True) if row['type'] == 'directory']
    # A local directory scan reports no inode on Windows and rename recovery needs one, so each
    # folder is asked about; a store that lists enough already said it, and asking again is a round
    # trip per folder per listing.
    live = listed if not isinstance(self.fs, LocalFileSystem) else [self.fs.info(row['name']) for row in listed]
    changed = False
    owner = self._owner(key)
    for child in folders:
      if any(self._key(row['name']) == child['path'] for row in live):
        continue
      matches = [row for row in live if row['type'] == 'directory' and row.get('ino') == child['ino']]
      if len(matches) != 1:
        continue
      old, new = child['path'], self._key(matches[0]['name'])
      self._existing_index(self._path(new))
      with self._database(owner, write=True) as database:
        stored = database.execute('SELECT path, metadata, children FROM gppufs_entries').fetchall()
        for path, metadata, members in stored:
          renamed = self._renamed_key(self._absolute(path, owner), old, new)
          renamed = self._relative(renamed, owner)
          if members is not None:
            values = json.loads(members)
            for value in values:
              renamed_child = self._renamed_key(self._absolute(value['path'], owner), old, new)
              value['path'] = self._relative(renamed_child, owner)
            members = json.dumps(values)
          value = json.loads(metadata)
          value['name'] = renamed
          value['gppu']['path'] = renamed
          database.execute('UPDATE gppufs_entries SET path=?, metadata=?, children=? WHERE path=?',
            (renamed, json.dumps(value), members, path))
      changed = True
    return changed

  @staticmethod
  def _modified(native: dict) -> datetime | None:
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

  def _inventory(self, fs: AbstractFileSystem, root: str) -> dict[str, dict]:
    # fsspec's archive info omits an empty archive root; it is still listable.
    native = {root: {'name': root, 'type': 'directory', 'size': 0}
      if isinstance(fs, AbstractArchiveFileSystem) and root in ('', '/') else fs.info(root)}
    if native[root]['type'] != 'directory' or native[root].get('islink'):
      return native
    if _probe_name(PurePosixPath(root).name, True).subtype == 'ignored':
      return native
    for _, directories, files in fs.walk(root, detail=True, on_error='raise'):
      for item in (*directories.values(), *files.values()):
        if not self._index_name.fullmatch(PurePosixPath(item['name']).name):
          native[item['name'].rstrip('/')] = fs.info(item['name'])
      for name in tuple(directories):
        if _probe_name(PurePosixPath(name).name, True).subtype == 'ignored' or directories[name].get('islink'):
          del directories[name]
    return native

  def _live(self, key: str, *, container: bool = False) -> None:
    """Parse what is at and below key, asked for with refresh=True: on this host in place; on any other store, or in
    an archive, each file a handler reads fetched alone into the cache, read and removed, nothing else fetched."""
    archive_metadata = self._stored(key)[0] if container else None
    with self._filesystem(key, container=container) as (fs, source):
      fs.invalidate_cache()
      native = self._inventory(fs, source)
      if isinstance(fs, LocalFileSystem):
        self._parse(key, Path(source), native, source)
      else:
        self._parse_listed(key, fs, native, source, in_archive=fs is not self.fs, archive_metadata=archive_metadata)

  def _parse_listed(self, key: str, fs: AbstractFileSystem, native: dict[str, dict], source: str, *,
                    in_archive: bool = False, archive_metadata: dict | None = None) -> None:
    """Parse a store's entries from its inventory: each identified by probe of its name, a file a handler reads
    fetched alone into the cache, parsed and removed. A folder is not read; its totals are what is below it."""
    rows: dict[str, tuple[dict, list[str] | None]] = {}
    now = datetime.now().astimezone()
    base = PurePosixPath(source)
    below: dict[str, list[str]] = {}
    for name in native:
      if name != source:
        below.setdefault(str(PurePosixPath(name).parent) if str(PurePosixPath(name).parent) != '.' else '', []).append(name)

    def read(name: str) -> tuple[str, dict]:
      item = native[name]
      relative = '.' if name == source else PurePosixPath(name).relative_to(base).as_posix()
      address = self._member_address(key, relative)
      directory = item['type'] == 'directory'
      record = _probe_name(PurePosixPath(name).name or 'location', directory, item.get('size'))
      handler, unread = handlers.HANDLERS.get((record.type, record.subtype)), None
      if not directory and handler not in (None, handlers.FileHandler):
        with _scratch('gppufs-file-') as scratch:
          copy = Path(scratch) / (''.join('_' if letter in UNSAFE else letter for letter in PurePosixPath(name).name) or 'entry')
          try:
            fs.get_file(name, str(copy))
            record = handler.parse(copy)
            record.meta['size'] = int(item.get('size') or 0)
          except Exception as error:   # the parse records what it could not read and goes on
            unread = f'{handler.__name__}: {type(error).__name__}: {error}'
            Warn(f'{self._uri(address)}: {unread}')
      children = [read(child) for child in sorted(below.get(name, ()), key=lambda child: (
        native[child]['type'] != 'directory', child.casefold()))] if directory else []
      row = self._row(address, item, record, Path(PurePosixPath(name).name or 'location'), probed_at=now, unread=unread,
                      children=[child for _, child in children] if directory else None)
      if name == source and archive_metadata is not None:
        row = archive_metadata
      rows[address] = row, [child_address for child_address, _ in children] if directory else None
      return address, row

    read(source)
    self._save(rows, key, in_archive=in_archive)

  @staticmethod
  def _member_address(key: str, relative: str) -> str:
    """The address of ``relative`` below any container, including an archive."""
    if relative == '.':
      return key
    return str(PurePosixPath(key) / relative)

  def _identify_inside(self, key: str) -> None:
    """Identify the archives on the way to an entry inside one, outermost first, each from its listing; no member
    is read."""
    parts = PurePosixPath(key).parts
    for n in range(1, len(parts) + 1):
      archive = PurePosixPath(*parts[:n]).as_posix()
      if not archive.casefold().endswith(handlers.ARCHIVES):
        continue
      if self._stored(archive) is None and self._archive_parent(archive) is None:
        self._identify_entry(archive)   # the physical archive, on the store itself
      stored = self._stored(archive)
      if stored is None or 'archive' not in stored[0]['gppu']['handlers']:
        return   # a folder named like an archive, or nothing there; the lookup answers that
      if stored[1] is None:
        self._identify_members(archive)

  def _identify_members(self, key: str) -> None:
    """Identify an archive's members from its listing, by probe from stand-ins of their names; no member is read."""
    metadata = self._stored(key)[0]
    with self._filesystem(key, container=True) as (fs, source):
      native = self._inventory(fs, source)
    rows: dict[str, tuple[dict, list | None]] = {key: (metadata, [])}
    members: dict[str, list[dict]] = {key: []}
    for name in sorted(native, key=lambda name: (native[name]['type'] != 'directory', name.casefold())):
      relative = PurePosixPath(name).relative_to(PurePosixPath(source)).as_posix() if source else name
      if relative in ('', '.') or self._index_name.fullmatch(PurePosixPath(name).name):
        continue
      address = self._member_address(key, relative)
      item = native[name]
      record = _probe_name(PurePosixPath(name).name, item['type'] == 'directory', item.get('size'))
      rows[address] = self._row(address, item, record, Path(PurePosixPath(name).name)), \
        [] if item['type'] == 'directory' else None
      parent = self._member_address(key, PurePosixPath(relative).parent.as_posix())
      members.setdefault(parent, []).append({'path': address, 'type': item['type'], 'ino': None})
    for address, listing in members.items():
      listing.sort(key=lambda entry: (entry['type'] != 'directory', entry['path'].casefold()))
      rows[address] = rows[address][0], listing
    self._store(key, rows, members[key])

  def _parse(self, key: str, local: Path, native: dict[str, dict], source: str, *,
             in_archive: bool = False, archive_metadata: dict | None = None) -> None:
    """Parse every entry at and below local through gppu's handlers, its native attributes from the fsspec
    inventory: each its handler's record, and a folder the totals of what is below it. A read that fails is
    the entry's `unread`, and the walk goes on."""
    local = full_path(local)
    rows: dict[str, tuple[dict, list[str] | None]] = {}
    now = datetime.now().astimezone()

    def read(path: Path) -> tuple[str, dict] | None:
      relative = path.relative_to(local).as_posix()
      name = str(PurePosixPath(source) / relative)
      name = '' if name == '.' else name
      if name not in native or self._index_name.fullmatch(path.name):
        return None
      item = native[name]
      address = self._member_address(key, relative)
      record, unread = handlers.probe(path), None
      handler = handlers.HANDLERS.get((record.type, record.subtype))
      if handler is not None and handler is not handlers.FolderHandler:
        try:
          record = handler.parse(path)
        except Exception as error:   # the walk records what it could not read and goes on
          unread = f'{handler.__name__}: {type(error).__name__}: {error}'
          Warn(f'{path}: {unread}')
      folder = self._folder(record)
      children: list[tuple[str, dict]] = []
      if folder:
        try:
          members = sorted(path.iterdir(), key=_display_order)
        except OSError as error:
          unread, members = f'listing: {type(error).__name__}: {error}', []
          Warn(f'{path}: {unread}')
        children = [child for member in members if (child := read(member)) is not None]
      row = self._row(address, item, record, path, probed_at=now, unread=unread,
                      children=[child for _, child in children] if folder else None)
      if path == local and archive_metadata is not None:
        row = archive_metadata
      rows[address] = row, [child_address for child_address, _ in children] if folder else None
      return address, row

    read(local)
    self._save(rows, key, in_archive=in_archive)

  def _archive_key(self, key: str) -> str:
    name = key.split('::', 1)[0].casefold()
    if name.endswith('.zip'):
      return 'zip://::' + key
    if name.endswith('.tar.gz'):
      return 'tar://::' + key
    if name.endswith('.rar'):
      return 'gppu-rar://::' + key
    raise ValueError(f'{key}: unsupported archive')

  def _identifiable(self, key: str) -> bool:
    """Every entry not inside an archive is identified from its listing, nothing fetched: on this host by probe, on
    any other store by probe of its name. An archive's members are identified from the archive's listing
    (`_identify_members`)."""
    return self._archive_parent(key) is None

  def _listed(self, key: str, item: dict) -> handlers.Record:
    """One entry of a store that is not this host's, identified by probe from its name, type and size as listed."""
    name = PurePosixPath(key).name if key != '.' else PurePosixPath(self.root).name or 'location'
    return _probe_name(name, item['type'] == 'directory', item.get('size'))

  @staticmethod
  def _folder(record: handlers.Record) -> bool:
    return record.subtype in (handlers.FolderHandler.subtype, handlers.SessionFolderHandler.subtype)

  @staticmethod
  def _span(value: Any) -> TimeSpan | None:
    """A span as a row holds it, [start, end], or as a record holds it."""
    if isinstance(value, TimeSpan) or value is None:
      return value
    return TimeSpan(datetime.fromisoformat(value[0]), datetime.fromisoformat(value[1]))

  def _own_span(self, gppu: dict) -> TimeSpan | None:
    """What a row's own record says of its time: its handler's span, else its name's."""
    return self._span(gppu['record'].get('span')) or handlers.Handler.named(gppu['record']['name'])

  def _totals(self, gppu: dict, children: list[dict] | None) -> dict:
    """A row's files, folders, bytes and span: a file is one file of its size; a folder the sum of what is below it,
    unknown while a child's is, its span its own and its children's together. Either spans its modified time when
    nothing says more."""
    modified = gppu['modified_at'] and datetime.fromisoformat(str(gppu['modified_at']))
    spans = [span for span in (self._own_span(gppu),) if span]
    if gppu['record']['subtype'] in handlers.IGNORED:
      return {'files': 0, 'folders': 0, 'bytes': 0, 'span': None}   # counted as ignored: never counted
    if children is None:
      totals = {'files': 1, 'folders': 0, 'bytes': gppu['size']}
    elif any(child['gppu']['files'] is None for child in children):
      return {'files': None, 'folders': None, 'bytes': None, 'span': None}
    else:
      totals = {'files': sum(child['gppu']['files'] for child in children),
                'folders': sum(child['gppu']['folders'] + (child['gppu']['type'] == 'folder') for child in children),
                'bytes': sum(child['gppu']['bytes'] for child in children)}
      spans += [span for child in children if (span := self._span(child['gppu']['span']))]
    span = TimeSpan(min(s.start for s in spans), max(s.end for s in spans)) if spans else (
      TimeSpan(modified, modified) if modified else None)
    return {**totals, 'span': span}

  def _row(self, key: str, item: dict, record: handlers.Record, path: Path, *, probed_at: datetime | None = None,
           unread: str | None = None, children: list[dict] | None = None) -> dict:
    """One entry as gppufs holds it: its native attributes, and under `gppu` the handlers that read it, its handler's
    record and its totals. An entry only identified, not parsed, is `probed` false, and a folder's totals are then
    unknown."""
    folder = self._folder(record)
    names = [record.subtype or record.type]
    if path.name.casefold().endswith(handlers.ARCHIVES):
      names.append('archive')
    located = self._location_of(path) if isinstance(self.fs, LocalFileSystem) else None
    if located is not None:
      names.append('location')
    gppu = {'path': str(path), 'type': 'folder' if folder else 'file',
            'size': 0 if folder else int(record.meta.get('size', 0)), 'modified_at': self._modified(item),
            'handlers': names, 'record': vars(record)}
    if located is not None:
      gppu['location'] = located
    if unread is not None:
      gppu['unread'] = unread
    gppu = json.loads(json.dumps(gppu, default=_metadata_text))
    if folder and probed_at is None:
      gppu.update(files=None, folders=None, bytes=None, span=None)
    else:
      gppu.update(json.loads(json.dumps(self._totals(gppu, children), default=_metadata_text)))
    gppu.update(is_container=folder or 'archive' in names, probed=probed_at is not None,
                probed_at=probed_at and str(probed_at))
    return {**item, 'name': self._uri(key), 'gppu': gppu}

  def _store(self, key: str, rows: dict[str, tuple[dict, list | None]], listing: list[dict] | None) -> None:
    """Add identified rows the index does not hold yet and record the folder's live child listing.

    What a handler read goes to the index first, so the next lookup is answered without running it,
    and then to the file beside the location, which is the cache.
    """
    if self._index is not None:
      keep: dict[str, tuple[dict | None, list[dict] | None]] = {
        self._address(child): (self._for_index(child, metadata),
                               None if members is None else
                               [{**item, 'path': self._address(item['path'])} for item in members])
        for child, (metadata, members) in rows.items()}
      if listing is not None:
        keep[self._address(key)] = (keep.get(self._address(key), (None, None))[0],
                                    [{**item, 'path': self._address(item['path'])} for item in listing])
      self._index.put(keep)
    grouped: dict[str, list[tuple]] = {}
    for child_key, (metadata, members) in rows.items():
      owner = self._owner(child_key)
      value = json.loads(json.dumps(metadata, default=_metadata_text))
      value['name'] = self._relative(child_key, owner)
      value['gppu']['path'] = value['name']
      grouped.setdefault(owner, []).append((value['name'], json.dumps(value, default=_metadata_text),
        None if members is None else json.dumps([
          {**entry, 'path': self._relative(entry['path'], owner)} for entry in members])))
    for owner, values in grouped.items():
      with self._database(owner, write=True) as database:
        database.executemany('INSERT INTO gppufs_entries VALUES (?, ?, ?) ON CONFLICT(path) DO NOTHING', values)
    if listing is None:
      return
    owner = self._owner(key)
    with self._database(owner, write=True) as database:
      database.execute('UPDATE gppufs_entries SET children=? WHERE path=?', (json.dumps([
        {**entry, 'path': self._relative(entry['path'], owner)} for entry in listing]), self._relative(key, owner)))

  def _identify_entry(self, key: str) -> None:
    """Index one entry from its native attributes and matching handlers, without probing."""
    path = self._path(key)
    item = self.fs.info(path)
    record = handlers.probe(Path(path)) if isinstance(self.fs, LocalFileSystem) else self._listed(key, item)
    self._store(key, {key: (self._row(key, item, record, Path(path)), None)}, None)

  def _unlocated(self, key: str) -> bool:
    """Whether the index holds this entry from before a configured location covered it.

    The location map is the caller's, not the folder's, so a row identified without it is
    out of date the moment the configuration names the place. Such a row is identified
    again; every other stored row is kept.
    """
    if not self._locations or not self._location_of(Path(self._path(key))):
      return False
    stored = self._stored(key)
    return stored is not None and 'location' not in stored[0]['gppu']

  def _forget(self, key: str) -> None:
    """Drop one stored entry so it is identified again on this listing."""
    owner = self._owner(key)
    with self._database(owner, write=True) as database:
      database.execute('DELETE FROM gppufs_entries WHERE path=?', (self._relative(key, owner),))

  def _reconcile(self, key: str, children: list[dict]) -> list[dict]:
    """List the folder live: identify entries the index has not seen, drop entries that are gone."""
    known = {child['path']: child for child in children}
    rows: dict[str, tuple[dict, list | None]] = {}
    listing: list[dict] = []
    local = isinstance(self.fs, LocalFileSystem)
    for entry in self.fs.ls(self._path(key), detail=True):
      name = entry['name'].rstrip('/')
      if self._index_name.fullmatch(PurePosixPath(name).name):
        continue
      child_key = self._key(name)
      if self._unlocated(child_key):
        self._forget(child_key)   # the stored row predates the location; an insert alone would keep it
      elif child_key in known:
        listing.append(known[child_key])
        continue
      if local:
        item = self.fs.info(name)  # A directory scan reports no inode on Windows; rename recovery needs it.
        record = handlers.probe(Path(self._path(child_key)))
      else:
        item = entry            # a store that lists enough said it all once; asking again is a call per entry
        record = self._listed(child_key, item)
      rows[child_key] = self._row(child_key, item, record, Path(self._path(child_key))), None
      listing.append({'path': child_key, 'type': item['type'], 'ino': item.get('ino')})
    listing.sort(key=lambda entry: (entry['type'] != 'directory', entry['path'].casefold()))
    if rows or listing != children:
      self._store(key, rows, listing)
    return listing

  @sync
  async def info(self, path: str | Path | None = None, refresh: bool = False, **kwargs) -> dict:
    """Return one native entry with its handler metadata.

    Awaited inside an event loop, called plainly outside one, as gppu's sync makes it.
    A physical entry the index has not seen is identified by probe, nothing read;
    ``refresh=True`` parses it. A folder's totals come from the last refresh of that folder.
    """
    return self.info_sync(path, refresh)

  def stored(self, path: str | Path | None = None) -> tuple[dict, list[dict] | None] | None:
    """What the index holds of path, its metadata and the listing of what is in it, touching no filesystem; None when it holds
    nothing. The listing is None until the folder was listed."""
    with self._lock:
      return self._stored(self._key(path))

  def info_sync(self, path: str | Path | None = None, refresh: bool = False) -> dict:
    """``info`` on the calling thread."""
    with self._lock:
      key = self._key(path)
      if not refresh and self._unlocated(key):
        self._forget(key)   # the stored row predates the location, as _reconcile treats a child
      cached = None if refresh else self._stored(key)
      if cached is None:
        physical = key
        for parent in reversed(PurePosixPath(physical).parents):
          parent_key = parent.as_posix()
          listing = self._stored(parent_key)
          if listing is not None and listing[1] is not None and self.fs.isdir(self._path(parent_key)):
            self._folder_renames(parent_key, listing[1])
        if not refresh:
          cached = self._stored(key)
      if cached is None and not refresh and self._identifiable(key):
        self._identify_entry(key)
        cached = self._stored(key)
      elif cached is None and not refresh:
        self._identify_inside(key)   # a member is known from its archives' listings
        cached = self._stored(key)
      if cached is None and refresh:
        self._live(key)
        cached = self._stored(key)
      if cached is None:
        raise FileNotFoundError(self._uri(key))
      return cached[0]

  @sync
  async def ls(self, path: str | Path | None = None, detail: bool = True,
               recurse: bool = False, refresh: bool = False, live: bool = True, **kwargs) -> list:
    """List entries, optionally descending, from the live folder and the colocated SQLite index.

    Awaited inside an event loop, called plainly outside one, as gppu's sync makes it.
    Every entry the listing finds is identified, nothing read. Entries already
    indexed keep their indexed metadata. ``refresh=True`` parses the folder and
    everything below it. An archive is opened only when it is listed itself;
    its members are identified from its listing, and refreshing the archive
    parses them one at a time. A recursion enters an archive whose listing the
    index holds, and opens none.
    """
    return self.ls_sync(path, detail, recurse, refresh, live)

  def ls_sync(self, path: str | Path | None = None, detail: bool = True,
              recurse: bool = False, refresh: bool = False, live: bool = True) -> list:
    """``ls`` on the calling thread.

    ``live`` reads the folder and reconciles the index with it. ``live=False`` answers from the
    index alone and touches no filesystem, so what was indexed is listed wherever this runs, and
    a folder the index has never seen lists nothing.
    """
    with self._lock:
      key = self._key(path)
      if live:
        metadata = self.info_sync(path, refresh=refresh)
        if 'archive' in metadata['gppu']['handlers']:
          if refresh:
            self._live(key, container=True)
          elif self._stored(key)[1] is None:
            self._identify_members(key)
      cached = self._stored(key)
      if cached is None:
        if not live:
          return []                                   # the index has never seen it
        raise FileNotFoundError(self._uri(key))
      current, children = cached
      archive = 'archive' in current['gppu']['handlers']
      if current['type'] != 'directory' and not archive:
        return [current] if detail else [current['name']]
      if not live:
        children = children or []                   # the index alone; the folder is not read
      elif not archive and self._identifiable(key):
        if children is not None and self._folder_renames(key, children):
          current, children = self._stored(key)
        children = self._reconcile(key, children or [])
      elif children is None:
        self._identify_inside(key)   # a folder in an archive is known from its archives' listings
        current, children = self._stored(key)
      elif not archive and self._folder_renames(key, children):
        current, children = self._stored(key)
      result = []
      for child in children:
        cached = self._stored(child['path'])
        if cached is None:
          continue
        row = cached[0]
        if recurse and (row['gppu']['type'] == 'folder' or (row['gppu']['is_container'] and cached[1] is not None)):
          # a recursion enters folders, and an archive only when the index holds its listing: it never opens one
          below = self.ls_sync(row['name'], recurse=True, live=live)
          result.append(row)
          result.extend(below)
        else:
          result.append(row)
      return result if detail else [row['name'] for row in result]

  def cp_file(self, path1: str | Path, path2: str | Path, **kwargs: Any) -> None:
    """Copy one entry's bytes inside this location. The copy is a new thing and is identified as one."""
    with self._lock:
      source, destination = self._key(path1), self._key(path2)
      self.fs.cp_file(self._path(source), self._path(destination), **kwargs)
      self._forget(destination)

  def rm_file(self, path: str | Path) -> None:
    """Remove one entry, and forget what was stored of it."""
    with self._lock:
      key = self._key(path)
      self.fs.rm_file(self._path(key))
      self._forget(key)

  def mv(self, path1: str | Path, path2: str | Path, recursive: bool = False,
         maxdepth: int | None = None, **kwargs: Any) -> None:
    """Move an entry, and move what is held of it with it.

    Alex's reason for a file manager on this filesystem: a folder moved between two indexed places
    keeps its index. So the bytes are renamed where the base filesystem can rename them — one
    operation for a folder of a million files, rather than a copy and a delete — and the rows under
    the old address are rewritten to the new one rather than dropped and read again.

    fsspec's own `mv` is a copy followed by a delete, which for a folder of that size is neither.
    """
    with self._lock:
      source, destination = self._key(path1), self._key(path2)
      if source == destination:
        return
      self.fs.mv(self._path(source), self._path(destination), recursive=recursive,
                 maxdepth=maxdepth, **kwargs)
      self._move_rows(source, destination)
      if self._index is not None:
        self._index.moved(self._address_of(source), self._address(destination))

  def move_into(self, other: 'GppuFileSystem', path: str | Path, destination: str | Path) -> str:
    """Move an entry out of this location and into another one, and move what is held of it with it.

    This is the move Alex asks a file manager for: a folder carried between two indexed places, where
    what the index says about it goes with it rather than being read again. The entity keeps its uid,
    so every annotation on it survives the move; only where it is changes.

    Two folders on one disk are renamed, which is one operation whatever the folder holds. Two places
    on different filesystems are copied and then removed, because there is no other way.

    The file beside each location is a cache and is treated as one: this location forgets what moved,
    and the other identifies what arrived when it next lists. The index is what carries the reading.
    """
    source, arriving = self._key(path), other._key(destination)
    was, now = self._address(source), other._address(arriving)
    here, there = self._path(source), other._path(arriving)
    if type(self.fs) is type(other.fs) and isinstance(self.fs, LocalFileSystem):
      self.fs.mv(here, there, recursive=True)
    else:
      other.fs.mkdirs(other._path(other._parent_key(arriving) or '.'), exist_ok=True)
      self.fs.get(here, there, recursive=True) if self.fs.isdir(here) else other.fs.pipe_file(
        there, self.fs.cat_file(here))
      self.fs.rm(here, recursive=True)
    with self._lock:
      self._forget_below(source)
    if self._index is not None:
      self._index.moved(was, now)
    return now

  def _forget_below(self, key: str) -> None:
    """Forget the stored rows at and under one key, and the listing of the folder it was in."""
    owner = self._owner(key)
    with self._database(owner, write=True) as database:
      if database is None:
        return
      here = self._relative(key, owner)
      database.execute('DELETE FROM gppufs_entries WHERE path=? OR substr(path,1,?)=?',
                       (here, len(here) + 1, here + '/'))
      parent = self._parent_key(key)
      if parent is not None:
        database.execute('UPDATE gppufs_entries SET children=NULL WHERE path=?',
                         (self._relative(parent, owner),))

  def preserve(self, folder: str | Path) -> Path | None:
    """Put this location's index in `folder` with its provenance in the name, and leave the location clean.

    Alex, 2026-09-17: an index that makes a folder unclean or unsynced — a repository's working tree, a
    library that will not sync a database — is preserved as a file in the lake rather than left where it
    is, and there it is a record, indexed as a file, not opened. The walk still writes one while it
    works; this is what happens at the end of the walk.

    Where the lake is is the caller's: this library knows what the file is, not where his lake keeps it.
    """
    if not isinstance(self.fs, LocalFileSystem):
      return None
    index = self._existing_index(self.root)
    if index is None:
      return None
    here = Path(index)
    kept = Path(folder) / f'{datetime.now().strftime("%y%m%d")} {socket.gethostname().casefold()} {here.name.lstrip(".")}'
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(here.read_bytes())
    if kept.read_bytes() != here.read_bytes():                 # compared by content, never by checksum
      raise OSError(f'{kept}: the preserved copy does not match {here}')
    here.unlink()
    with self._lock:
      self._memory.clear()
    return kept

  def _address_of(self, key: str) -> str:
    """The address an entry had, worked out from the location map rather than from the vanished path."""
    if self._locations:
      for folder in sorted(self._locations, key=lambda item: len(item), reverse=True):
        here = full_path(Path(self._path(key))).as_posix()
        base = folder.rstrip('/')
        if here == base or here.startswith(base + '/'):
          return _address(str(self._locations[folder]['canonical']), '' if here == base else here[len(base) + 1:])
    return self._uri(key)

  def _move_rows(self, source: str, destination: str) -> None:
    """Rewrite every stored row at and under `source` to sit under `destination`."""
    owner = self._owner(source)
    if owner != self._owner(destination):
      self._forget(source)                       # two indexes; the new place identifies what arrived
      return
    with self._database(owner, write=True) as database:
      if database is None:
        return
      here, there = self._relative(source, owner), self._relative(destination, owner)
      for path, metadata, children in database.execute(
          'SELECT path, metadata, children FROM gppufs_entries').fetchall():
        if path != here and not path.startswith(here + '/'):
          continue
        moved = there + path[len(here):]
        value = json.loads(metadata)
        value['name'] = moved
        value['gppu']['path'] = moved
        listing = children if children is None else json.dumps([
          {**child, 'path': there + child['path'][len(here):]
           if child['path'] == here or child['path'].startswith(here + '/') else child['path']}
          for child in json.loads(children)])
        database.execute('DELETE FROM gppufs_entries WHERE path=?', (path,))
        database.execute('INSERT INTO gppufs_entries VALUES (?, ?, ?) '
          'ON CONFLICT(path) DO UPDATE SET metadata=excluded.metadata, children=excluded.children',
          (moved, json.dumps(value), listing))
      parent = self._parent_key(destination)
      if parent is not None:
        database.execute('UPDATE gppufs_entries SET children=NULL WHERE path=?',
                         (self._relative(parent, owner),))

  def _open(self, path: str | Path | None = None, mode: str = 'rb', **kwargs) -> BinaryIO:
    """The bytes of one entry: a physical file through the base filesystem, a member through its archive.

    fsspec builds `cat_file`, `open`, `head`, `tail`, `get_file`, `pipe_file` and `read_text` on this
    one call, and its own default reads through `cat_file`, which reads through `_open` — so a
    filesystem that leaves `_open` alone recurses until the stack ends.

    Bytes are the base filesystem's, and the index is not touched: a write changes the file, and what
    was identified stands until the folder is read again with `refresh=True`, exactly as it does for a
    file some other writer changed.
    """
    key = self._key(path)
    if self._archive_parent(key) is None:
      return self.fs._open(self._path(key), mode, **kwargs)
    if 'r' not in mode:
      raise ValueError(f'{self._uri(key)}: a member of an archive is read-only')
    with self._filesystem(key) as (fs, source):
      return io.BytesIO(fs.cat_file(source))


class PostgresFileSystem(AbstractFileSystem):
  """A Postgres database read as folders and entries, so gppufs can index one like any other place.

  Alex, 2026-09-17 04:21: an index in Postgres of his other Postgres databases and tables, every
  database, schema and table written down as a source of data he may or may not trust yet. gppufs and
  the handlers are how everything reads files, so a database is read the same way rather than by a
  script of its own: a schema is a folder, a table or view is an entry in it, and what `pg_catalog`
  knows about each is its metadata.

      GppuFileSystem('pg://pg.karel.in/files', dsn='postgresql://…')

  `dsn` is the caller's, because which databases exist and how one connects to them is his
  configuration and not this library's. Nothing here writes: a database is read, never indexed into.
  """

  protocol = 'pg'
  cachable = False
  root_marker = ''

  SCHEMAS = ("select nspname from pg_namespace"
             " where nspname not like 'pg\\_%' and nspname <> 'information_schema' order by nspname")
  ENTRIES = ("select c.relname as name, c.relkind as kind,"
             "       pg_total_relation_size(c.oid) as bytes, c.reltuples::bigint as rows,"
             "       obj_description(c.oid) as comment"
             "  from pg_class c join pg_namespace n on n.oid = c.relnamespace"
             " where n.nspname = %s and c.relkind in ('r', 'v', 'm', 'p', 'f') order by c.relname")
  COLUMNS = ("select a.attname, format_type(a.atttypid, a.atttypmod) as type, a.attnotnull"
             "  from pg_attribute a join pg_class c on c.oid = a.attrelid"
             "  join pg_namespace n on n.oid = c.relnamespace"
             " where n.nspname = %s and c.relname = %s and a.attnum > 0 and not a.attisdropped"
             " order by a.attnum")
  KINDS = {'r': 'table', 'v': 'view', 'm': 'materialized view', 'p': 'partitioned table',
           'f': 'foreign table'}

  # -- when a table's records happened ---------------------------------------------------------
  # Alex, 2026-09-17: "Every entity has a date. It can be called date_sent or date_created, but
  # every entity has a date. Timestamps of systems that process entities should never be used."
  #
  # So a table's span is the range its own records cover, read from the entity's own date and never
  # from the stamp a loader left. `loaded_at`, `indexed_at`, `read_at` say when something read the
  # row, not when the thing happened, and a span read off one of those says every table covers the
  # hour the loader ran. They are left out by name; what remains is judged by what it holds, and the
  # widest real range wins, because a record's own date spreads over the life of the data while a
  # processing stamp collapses into the run that wrote it.
  PROCESSED = ('loaded', 'indexed', 'read', 'seen', 'gone', 'ingested', 'imported', 'synced',
               'probed', 'analysed', 'analyzed', 'refreshed', 'fetched', 'crawled', 'scanned',
               'exported', 'processed', 'harvested', 'dumped', 'etl')
  # A bare verb and `_at` is the stamp on the row, written when the row was written: an index's
  # `created_at` is when it indexed the thing, not when the thing was created. A date of the thing
  # says so in its name — `date_created`, `date_sent`, `changed_at` for a file's own mtime — which
  # is the difference between his two examples. A table whose only date is a row stamp has no date
  # of its own and gets no span, which is truer than a span of when the loader ran.
  STAMPS = ('created_at', 'updated_at', 'inserted_at', 'written_at', 'recorded_at', 'stored_at')
  # The day each system's clock starts from, which is what it writes where a date is unknown. Read
  # off his own databases: .NET's minimum, Excel and OLE's zero, SQL Server's, and Unix's in both
  # the spellings a stored value takes here.
  ZEROS = ('0001-01-01', '0001-12-31', '1899-12-30', '1899-12-31', '1900-01-01',
           '1969-12-31', '1970-01-01')
  DATED = ("select a.attname from pg_attribute a join pg_class c on c.oid = a.attrelid"
           "  join pg_namespace n on n.oid = c.relnamespace"
           " where n.nspname = %s and c.relname = %s and a.attnum > 0 and not a.attisdropped"
           "   and a.atttypid in ('timestamptz'::regtype, 'timestamp'::regtype, 'date'::regtype)"
           " order by a.attnum")

  def dated(self, schema: str, name: str) -> list[str]:
    """The columns of a table that could carry the date of the thing each row is."""
    with self._asking() as cursor:
      cursor.execute(self.DATED, (schema, name))
      found = [row['attname'] for row in cursor.fetchall()]
    return [column for column in found
            if column.casefold() not in self.STAMPS
            and not any(word in column.casefold() for word in self.PROCESSED)]

  def span(self, path: str) -> dict[str, Any] | None:
    """When one table's records happened: the column their date is in, and its first and last.

    A zero is not a date. Where the date was unknown a system writes the day its own clock starts
    from, and every one of them reads as a real date: Unix writes 1970-01-01, or the evening of
    1969-12-31 when it was stored without a zone in a western one; .NET writes 0001-01-01; Excel and
    OLE write 1899-12-30; SQL Server writes 1900-01-01. Taking any of them says the table begins at
    the beginning of that system's time. They are left out of the reading rather than corrected in
    the data, and nothing is clamped: a date that is merely old, a photograph from 1967, is a date.
    """
    schema, _, name = self._under(path).partition('/')
    columns = self.dated(schema, name) if name else []
    if not columns:
      return None
    zeros = ', '.join(f"'{day}'" for day in self.ZEROS)
    real = '("{0}"::date <> all(array[' + zeros + ']::date[]))'
    reads = ', '.join(f'min("{column}") filter (where {real.format(column)}) as "from_{i}",'
                      f' max("{column}") filter (where {real.format(column)}) as "to_{i}"'
                      for i, column in enumerate(columns))
    with self._asking() as cursor:
      cursor.execute(f'select {reads} from "{schema}"."{name}"')   # noqa: S608 - names from pg_catalog
      read = list(cursor.fetchone().values())
    widest = None
    for column, first, last in zip(columns, read[::2], read[1::2]):
      if first is None or last is None:
        continue
      if widest is None or (last - first) > (widest['last'] - widest['first']):
        widest = {'column': column, 'first': first, 'last': last}
    return widest

  def __init__(self, database: str, dsn: str | None = None, **storage_options: Any) -> None:
    if not dsn:
      raise ValueError('a Postgres location is read with a dsn; which databases exist is configuration')
    super().__init__()
    self.root = self._strip_protocol(database)
    self.dsn = dsn
    self.location = f'pg://{self.root}'

  @classmethod
  def _strip_protocol(cls, path: str) -> str:
    path = stringify_path(path)
    for prefix in ('pg://', 'postgresql://', 'postgres://'):
      if path.startswith(prefix):
        path = path[len(prefix):]
    return path.strip('/')

  @contextmanager
  def _asking(self):
    import psycopg2                                            # noqa: PLC0415 - the pg extra, asked for here only
    from psycopg2.extras import RealDictCursor                 # noqa: PLC0415
    with closing(psycopg2.connect(self.dsn)) as connection:
      with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        yield cursor

  def _under(self, path: str) -> str:
    """What is asked about, below this database: '' for the database, else the schema or schema/entry."""
    here = self._strip_protocol(path or '')
    return here[len(self.root):].strip('/') if here.startswith(self.root) else here

  def ls(self, path: str = '', detail: bool = True, **kwargs: Any) -> list:
    """The schemas of a database, or the tables and views of a schema."""
    under = self._under(path)
    with self._asking() as cursor:
      if not under:
        cursor.execute(self.SCHEMAS)
        found = [{'name': f'{self.root}/{row["nspname"]}', 'type': 'directory', 'size': 0}
                 for row in cursor.fetchall()]
      else:
        cursor.execute(self.ENTRIES, (under,))
        found = [{'name': f'{self.root}/{under}/{row["name"]}', 'type': 'file',
                  'size': int(row['bytes'] or 0), 'kind': self.KINDS.get(row['kind'], row['kind']),
                  'rows': int(row['rows'] or 0), 'comment': row['comment']}
                 for row in cursor.fetchall()]
    return found if detail else [row['name'] for row in found]

  def info(self, path: str = '', **kwargs: Any) -> dict:
    """What one schema or one entry is."""
    under = self._under(path)
    if not under:
      return {'name': self.root, 'type': 'directory', 'size': 0}
    schema, _, name = under.partition('/')
    if not name:
      return {'name': f'{self.root}/{schema}', 'type': 'directory', 'size': 0}
    for row in self.ls(f'{self.root}/{schema}'):
      if row['name'].rsplit('/', 1)[-1] == name:
        return row
    raise FileNotFoundError(f'pg://{self.root}/{under}')

  def _open(self, path: str, mode: str = 'rb', **kwargs: Any) -> BinaryIO:
    """One entry's columns, as text, so what a table holds can be read and identified like a file."""
    if 'r' not in mode:
      raise ValueError(f'pg://{self.root}: a database is read here, never written')
    schema, _, name = self._under(path).partition('/')
    with self._asking() as cursor:
      cursor.execute(self.COLUMNS, (schema, name))
      columns = cursor.fetchall()
    text = '\n'.join(f'{row["attname"]} {row["type"]}'
                      + ('' if not row['attnotnull'] else ' not null') for row in columns)
    return io.BytesIO(text.encode('utf-8'))

  def created(self, path: str) -> None:
    return None

  def modified(self, path: str) -> None:
    return None


register_implementation('pg', PostgresFileSystem, clobber=True)


class SharePointFileSystem(AbstractFileSystem):
  """A SharePoint or OneDrive drive read as folders and files, so gppufs can index one like any other place.

  The address is Alex's, written down in his FileIndexer inventory: ``m365://$tenant/$service/$path``,
  with ``sharepoint`` and ``onedrive`` as sibling services of a tenant. The last name of the path is
  the drive and what comes before it is the site, so a document library is a Location the way a
  Synology share is one.

      GppuFileSystem('m365://karelin/sharepoint/teams/Alex/Finance', token=lambda: '...')

  ``token`` is the caller's: which app registration reaches which tenant is his configuration and
  not this library's. Nothing here writes. A drive is read, never written to.

  A listing carries each item's SharePoint metadata with it, in the call that lists the folder:
  the content type and every custom column come back with the item, so what a library says about a
  document is in the index without the document being opened. That is also why this store sets
  ``listing_is_enough``: its listing gives a name, a type and a size, which is what identification
  asks about, and only a file that is probed is ever fetched.
  """

  protocol = 'm365'
  cachable = False
  root_marker = ''
  listing_is_enough = True

  GRAPH = 'https://graph.microsoft.com/v1.0'
  # The content type and every custom column arrive with the item; this is the whole of the metadata.
  EXPAND = 'listItem($expand=fields)'
  PAGE = 200
  DEADLINE = (10, 120)          # seconds to reach Graph, and to wait for it to answer
  PATIENCE = 6                  # how many times a throttled call is asked again before it is raised
  LONGEST_WAIT = 120            # seconds, whatever Retry-After says

  def __init__(self, tenant: str, service: str, site: str, drive: str,
               token: Callable[[], str] | None = None, **storage_options: Any) -> None:
    if token is None:
      raise ValueError('a SharePoint location is read with a token; which app reaches a tenant is configuration')
    super().__init__()
    self.tenant, self.service, self.site, self.drive = tenant, service, site, drive
    self.token = token
    self.root = '/'.join(part for part in (tenant, service, site, drive) if part)
    self.location = f'm365://{self.root}'
    self.host = f'{tenant}-my.sharepoint.com' if service == 'onedrive' else f'{tenant}.sharepoint.com'
    self._drive_id: str | None = None
    self._asked = None               # one pooled connection: a walk is thousands of calls to one host

  @classmethod
  def _get_kwargs_from_urls(cls, path: str) -> dict[str, str]:
    """The tenant, the service, the site and the drive, read out of the address itself."""
    parts = [part for part in cls._strip_protocol(path).split('/') if part]
    if len(parts) < 3:
      raise ValueError(f'{path}: an m365 location is m365://tenant/service/site/drive')
    return {'tenant': parts[0], 'service': parts[1], 'site': '/'.join(parts[2:-1]), 'drive': parts[-1]}

  @classmethod
  def _strip_protocol(cls, path: str) -> str:
    path = stringify_path(path)
    return (path[len('m365://'):] if path.startswith('m365://') else path).strip('/')

  def _asking(self, url: str, params: dict[str, str] | None = None):
    """One call to Graph, waited on for a bounded time and asked again while Graph says to wait.

    A walk of a tenant is hundreds of thousands of calls. Without a deadline one stalled read stops
    the walk for good and says nothing, which is how a library comes to be missing from an index
    that reports no error. Graph also throttles a walk of this size as a matter of course and says
    with 429 how long to wait; waiting as told is its protocol rather than a way around a failure.
    Everything else is raised.
    """
    import requests                                             # noqa: PLC0415 - the m365 extra, asked for here only
    if self._asked is None:
      self._asked = requests.Session()
    where = url if url.startswith('https://') else f'{self.GRAPH}/{url.lstrip("/")}'
    for attempt in range(self.PATIENCE):
      response = self._asked.get(where, headers={'Authorization': f'Bearer {self.token()}'},
                                 params=params, timeout=self.DEADLINE)
      if response.status_code not in (429, 503, 504):
        break
      if attempt == self.PATIENCE - 1:
        raise OSError(f'{response.status_code} {where}: still asked to wait after {self.PATIENCE} tries')
      time.sleep(min(int(response.headers.get('Retry-After', 2 ** attempt)), self.LONGEST_WAIT))
    if response.status_code == 404:
      raise FileNotFoundError(url)
    if response.status_code >= 400:
      raise OSError(f'{response.status_code} {where}: {response.text[:200]}')
    return response

  def _identity(self) -> str:
    """The drive this Location is, resolved once from the site and the drive's own name."""
    if self._drive_id is None:
      address = f'sites/{self.host}:/{self.site}:' if self.site else f'sites/{self.host}'
      site = self._asking(address).json()
      for found in self._asking(f'sites/{site["id"]}/drives?$select=id,name').json()['value']:
        if found['name'] == self.drive:
          self._drive_id = found['id']
          break
      else:
        raise FileNotFoundError(f'{self.location}: the site has no drive named {self.drive}')
    return self._drive_id

  def _under(self, path: str) -> str:
    """What is asked about, below this drive: '' for the drive itself, else the item's path in it."""
    here = self._strip_protocol(path or '')
    return here[len(self.root):].strip('/') if here.startswith(self.root) else here

  def _address(self, under: str) -> str:
    return f'drives/{self._identity()}/root' + (f':/{quote(under)}:' if under else '')

  def _entry(self, item: dict, under: str) -> dict:
    """One item as this store lists it: what it is, and what SharePoint says about it."""
    listed = item.get('listItem') or {}
    return {'name': f'{self.root}/{under}'.rstrip('/') if under else self.root,
            'type': 'directory' if 'folder' in item else 'file',
            'size': int(item.get('size') or 0),
            'mtime': item.get('lastModifiedDateTime'),
            'ino': item.get('id'),
            'etag': item.get('eTag'),
            'created_at': item.get('createdDateTime'),
            'web_url': item.get('webUrl'),
            'content_type': (listed.get('contentType') or {}).get('name'),
            'columns': listed.get('fields') or {}}

  def ls(self, path: str = '', detail: bool = True, **kwargs: Any) -> list:
    """What is directly in one folder of the drive, each entry carrying its SharePoint metadata."""
    under = self._under(path)
    url = f'{self.GRAPH}/{self._address(under)}/children'
    params: dict[str, str] | None = {'$expand': self.EXPAND, '$top': str(self.PAGE)}
    found = []
    while url:
      page = self._asking(url, params).json()
      params = None                       # the next link carries the query it was made with
      for item in page.get('value', []):
        found.append(self._entry(item, f'{under}/{item["name"]}'.lstrip('/')))
      url = page.get('@odata.nextLink')
    return found if detail else [row['name'] for row in found]

  def info(self, path: str = '', **kwargs: Any) -> dict:
    """What one item is, with its content type and its custom columns."""
    under = self._under(path)
    item = self._asking(self._address(under), {'$expand': self.EXPAND}).json()
    return self._entry(item, under)

  def _open(self, path: str, mode: str = 'rb', **kwargs: Any) -> BinaryIO:
    """One item's bytes, fetched only when something asks to read it."""
    if 'r' not in mode:
      raise NotImplementedError(f'{self.location}: a drive is read here, never written')
    return io.BytesIO(self._asking(f'{self._address(self._under(path))}/content').content)

  def created(self, path: str) -> None:
    return None

  def modified(self, path: str) -> None:
    return None


class GppuCatalog(AbstractFileSystem):
  """A catalog of Locations keyed by uid.

  After ``Env.from_env(...)`` or ``Env.from_dict(...)``, ``GppuCatalog()``
  resolves the configured connections and nested Locations. ``ls(recurse=True)``
  walks that configuration tree. ``location(uid)`` returns the Location whose
  ``ls`` and ``walk`` enumerate its child Locations. An explicit mapping
  accepts the same data from another configuration loader.

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
  them. Every address at or below a Location is served by that Location's
  :class:`GppuFileSystem`; the deepest Location whose root contains the address
  owns it. A Location root's parent is its parent Location when the catalog
  names one, otherwise the catalog root, so a browser walks the Locations tree.
  """

  protocol = 'gppu-catalog'
  cachable = False

  def __init__(self, catalog: str | Path | Mapping | None = None, host: str | None = None,
               location_types: Mapping | None = None, templates: Mapping[str, str] | None = None) -> None:
    self.location_types = {'file': FileSystem}
    if location_types is not None:
      self.location_types.update(location_types)
    self.templates = templates
    self._providers: dict[str | None, Provider] = {}
    self._configuration = catalog is None or isinstance(catalog, Mapping)
    if self._configuration:
      if catalog is None:
        if not Env.initialized:
          raise RuntimeError('load configuration with Env before constructing GppuCatalog')
        catalog = Env.glob_dict('')
      super().__init__()
      self.host = host or socket.gethostname().split('.')[0].lower()
      self.root = 'gppu-catalog://'
      self._lock = RLock()
      self._config = deepcopy(dict(catalog))
      self._bound_locations = {}
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
    self._filesystems: dict[str, GppuFileSystem] = {}
    self._load()

  def _load_configuration(self) -> None:
    """Resolve configured Locations without opening any provider or index.

    The input is the tree already loaded by Env, or the same plain data returned
    by a database loader. Nested paths are provider-relative, never appended to
    their parent's path. Loading does not mutate Env or the supplied mapping.
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
    """Return the Location with this UID, with the Provider of its connection.

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
        self._bound_locations[uid] = Location(row,
          provider=self._provider(urlsplit(row['canonical']).scheme, row.get('connection')),
          parent=self.location(parent) if parent is not None else None,
          children=lambda: (self.location(child) for child, owner in self._parents.items() if owner == uid),
          templates=self.templates)
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

  def filesystem(self, uid: str) -> GppuFileSystem:
    """Indexing is explicitly selected; ingestion uses Location operations."""
    return GppuFileSystem(self.locations[uid]['canonical'])

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
      fs = self._filesystems.get(row['root_path']) or GppuFileSystem(row['root_path'])
      if Path(row['index']) != Path(fs._database_path(fs.root)):
        raise ValueError(f"{row['root_path']}: catalog index {row['index']} is not {fs._database_path(fs.root)}")
      self._filesystems[row['root_path']] = fs
      locations[row['root_path']] = row
    self.locations = locations
    by_id = {row['id']: row['root_path'] for row in rows}
    self._parents = {row['root_path']: by_id.get(row['parent_file_location_id']) for row in rows}

  def _location(self, path: str | Path) -> GppuFileSystem:
    """The Location serving an absolute address: the deepest one whose root contains it."""
    physical = str(path).replace('\\', '/')
    if '://' not in physical and not Path(physical).is_absolute():
      raise ValueError(f'{path}: catalog addresses are absolute paths or URLs')
    owners = []
    for fs in self._filesystems.values():
      try:
        fs._key(path)
      except ValueError:
        continue
      owners.append(fs)
    if not owners:
      raise FileNotFoundError(f'{path}: not inside a catalog Location')
    return max(owners, key=lambda fs: len(fs.root))

  def _parent(self, fs: GppuFileSystem) -> str:
    parent = self._parents[self._path_of(fs)]
    return self.root if parent is None else self._filesystems[parent].location

  def _path_of(self, fs: GppuFileSystem) -> str:
    return next(path for path, item in self._filesystems.items() if item is fs)

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
    rows = {path: self._location_row(fs)['gppu'] for path, fs in self._filesystems.items()}
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

  def _location_row(self, fs: GppuFileSystem) -> dict:
    """A Location as the catalog knows it: the catalog's row, with the totals and last refresh its own index holds."""
    row = self.locations[self._path_of(fs)]
    cached = fs._stored('.')
    known = cached[0]['gppu'] if cached is not None else {}
    return {'name': fs.location, 'type': 'directory', 'size': 0, 'gppu': {
      'name': PurePosixPath(fs.root).name or fs.root.rstrip('/'), 'path': fs.location, 'parent': self._parent(fs),
      'type': 'folder', 'modified_at': known.get('modified_at'), 'handlers': known.get('handlers', []),
      'files': known.get('files'), 'folders': known.get('folders'), 'bytes': known.get('bytes'),
      'span': known.get('span'), 'stats': known.get('stats', {}), 'probed': known.get('probed', False),
      'probed_at': known.get('probed_at'), 'is_container': True, 'indexed': cached is not None, 'location': row,
      **({'source': source} if (source := self._source(fs, '.')) is not None else {})}}

  def _source(self, fs: GppuFileSystem, key: str) -> dict | None:
    """What a folder is by the catalog: the canonical location it is a replica of on this host, or None."""
    return self._replicas.get(os.path.normcase(os.path.normpath(fs._path(key))))

  def _served(self, fs: GppuFileSystem, row: dict) -> dict:
    """A row from a Location's filesystem: its root carries the catalog's parent and Location, a replica its source."""
    extra = {}
    if row['name'] == fs.location:
      extra.update(parent=self._parent(fs), location=self.locations[self._path_of(fs)])
    if row['type'] == 'directory' and (source := self._source(fs, fs._key(row['name']))) is not None:
      extra['source'] = source
    return {**row, 'gppu': {**row['gppu'], **extra}} if extra else row

  @sync
  async def info(self, path: str | Path | None = None, refresh: bool = False, **kwargs) -> dict:
    """The catalog itself, or one entry served by its Location; awaited in a loop, called plainly outside one."""
    return self.info_sync(path, refresh)

  def info_sync(self, path: str | Path | None = None, refresh: bool = False) -> dict:
    """``info`` on the calling thread."""
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
      fs = self._location(path)
      return self._served(fs, fs.info_sync(path, refresh=refresh))

  @sync
  async def ls(self, path: str | Path | None = None, detail: bool = True,
               recurse: bool = False, refresh: bool = False, **kwargs) -> list:
    """The Locations at the catalog root, otherwise the listing the owning Location gives.

    Awaited inside an event loop, called plainly outside one. ``refresh=True``
    at the root rereads ``locations.yaml``. Recursion from the root descends
    the Locations that have no parent Location; their subtrees hold the rest.
    """
    return self.ls_sync(path, detail, recurse, refresh)

  def ls_sync(self, path: str | Path | None = None, detail: bool = True,
              recurse: bool = False, refresh: bool = False) -> list:
    """``ls`` on the calling thread."""
    with self._lock:
      if self._configuration:
        return self._configured_listing(path, detail, recurse, refresh)
      if path is None or path == self.root:
        if refresh:
          self._load()
        result = []
        for location in sorted(self._filesystems, key=str.casefold):
          fs = self._filesystems[location]
          if recurse and self._parents[location] is not None:
            continue
          result.append(self._location_row(fs))
          if recurse:
            result.extend(fs.ls_sync(None, recurse=True))
      else:
        fs = self._location(path)
        result = [self._served(fs, row) for row in fs.ls_sync(path, recurse=recurse, refresh=refresh)]
      return result if detail else [row['name'] for row in result]


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
         'handlers': [record.subtype or record.type], 'record': vars(record)}
  if name.casefold().endswith(handlers.ARCHIVES):
    row['handlers'].append('archive')
  if isinstance(record, handlers.Session) and record.uid:
    row['fingerprints'] = [('session', f'{record.subtype}/{record.uid}')]
  elif record.subtype == handlers.SessionFolderHandler.subtype and record.data.get('uid'):
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
  handler = handlers.HANDLERS.get((record.type, record.subtype))
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
        or handlers.HANDLERS.get((record.type, record.subtype)) not in (None, handlers.FileHandler))

    def folder(prefix: str, under: str) -> Iterator[tuple[dict, list[dict]]]:
      rows, descend, nested = [], [], []
      children = [member for member in listing if PurePosixPath(member).parent.as_posix() == (prefix or '.')]
      for member in sorted(children, key=lambda member: (listing[member]['type'] != 'directory', member.casefold())):
        item, record, unread = listing[member], identified[member], None
        name = f"{under}/{PurePosixPath(member).name}"
        kind = 'directory' if item['type'] == 'directory' else 'file'
        if kind == 'file' and (level == 'refresh' or record.subtype == 'ignored'):
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
        row = _walked(name, kind, item.get('size'), GppuFileSystem._modified(item), record, unread)
        if kind == 'directory':
          if PurePosixPath(member).name in FOLDER_CLASSES or record.subtype == 'ignored':
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
      folder_like = GppuFileSystem._folder(record)
      if record.subtype == 'ignored' and not entry.is_dir():
        continue
      if level == 'refresh' and not (folder_like or entry.is_dir()):
        continue
      stat = entry.lstat()
      row = _walked(name, 'directory' if entry.is_dir() else 'file', None if entry.is_dir() else stat.st_size,
                    handlers.Handler.valid_time(datetime.fromtimestamp(stat.st_mtime).astimezone()), record, unread)
      if record.subtype in ('symlink', 'junction'):
        row['boundary'] = 'link'
        row['target'] = str(entry.resolve())
      elif name in boundaries:
        row['boundary'] = 'Location'
      elif entry.is_dir():
        if entry.name in FOLDER_CLASSES or record.subtype == 'ignored':
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
  if record.subtype in ('symlink', 'junction'):
    raise PermissionError(f'{path}: a link cannot be selected for traversal')
  if record.subtype == 'ignored':
    raise PermissionError(f'{path}: selected directory is excluded by the ignore rules')
  if not GppuFileSystem._folder(record):
    raise NotADirectoryError(str(selected))
  yield from visit(selected, path)

# endregion
