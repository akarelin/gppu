"""Locations select Containers; Containers exchange source-addressed data."""
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
import filecmp
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import socket
import shutil
import tempfile
from typing import Any, BinaryIO
from urllib.parse import quote, unquote, urlsplit

from .gppu import TemplateSet, _Base, y2path, y2uri

@dataclass(frozen=True)
class DataObject:
  uri: y2uri
  content: dict[str, Any] | list[Any] | str | int | float | bool | None | bytes | BinaryIO
  identity: str | None
  kind: str = 'object'
  name: str = ''
  parent: 'DataObject | None' = None
  removed: bool = False

  def __post_init__(self) -> None:
    object.__setattr__(self, 'uri', y2uri(self.uri))


class Container:
  """Operations below a Location boundary, with source-owned refresh state."""

  def ls(self, path: y2path | str = '', detail: bool = True) -> list[dict[str, Any]] | list[str]:
    """Immediate folders and objects in this Container, using fsspec entries."""
    raise NotImplementedError

  def walk(self, path: y2path | str = '', *, level: str = 'files', recursive: bool = False,
           boundaries: Iterable[y2path | str] = ()) -> Iterator[tuple[dict, list[dict]]]:
    """Yield successfully enumerated folders and their immediate indexed entries.

    Paths remain relative to this Container. Explicit child Location boundaries
    are reported but never entered. Listing errors propagate to the indexer.
    """
    from .indexing import walk_container
    yield from walk_container(self, str(Location.relative(path)), level, recursive, boundaries)

  def read(self, path: y2path | str | DataObject) -> DataObject:
    """Read one object without changing a refresh cursor."""
    raise NotImplementedError

  def write(self, obj: DataObject) -> None:
    """Write the object's files."""
    raise NotImplementedError

  def delete(self, path: y2path | str | DataObject) -> None:
    """Explicitly remove an object before a deliberate replacement."""
    raise NotImplementedError

  def _refresh(self, state: dict[str, Any], path: y2path | str) -> AbstractContextManager[tuple[Iterator[DataObject], Callable[[], None]]]:
    """Yield objects and a callback updating the caller's refresh state."""
    raise NotImplementedError

  @contextmanager
  def refresh(self, state: dict[str, Any], path: y2path | str = '') -> Iterator[Iterator[DataObject]]:
    """Commit source state only after full iteration and successful handling.

    with source.refresh(state, folder) as changes:
      for obj in changes:
        destination.write(obj)
    """
    with self._refresh(state, path) as (objects, commit):
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


class Location(_Base):
  """A Location in the tree, constructed from configuration or enumeration."""

  def __init__(self, properties: dict[str, Any], *, connection: dict[str, Any] | None = None,
               parent: 'Location | None' = None,
               children: Callable[[], Iterable['Location']] | None = None) -> None:
    super().__init__()
    self._config_from_dict(properties)
    self.uid = properties['uid']
    self.uri = y2uri(properties['canonical'])
    self.parent = parent
    self._connection = deepcopy(connection)
    self._children = children

  def walk(self) -> Iterator[tuple['Location', list['Location']]]:
    """Yield each Location and its immediate children, listing each node once."""
    children = self.ls()
    yield self, children
    for child in children:
      yield from child.walk()

  def ls(self) -> list['Location']:
    return list(self._children()) if self._children is not None else []

  def container(self, path: y2path | str = '') -> Container:
    raise NotImplementedError(f'{self.uri}: Containers are not implemented')

  def address(self, path: y2path | str = '') -> y2uri:
    """Canonical address of a relative path, with literal names URI-escaped."""
    path = self.relative(path)
    if not path:
      return self.uri
    return self.uri / quote(str(path), safe='/')

  @staticmethod
  def relative(path: y2path | str) -> y2path:
    if isinstance(path, y2path):
      path = str(path)
    if not isinstance(path, str) or path.startswith('/') or '\\' in path or '://' in path:
      raise ValueError('Location path must be relative and slash-separated')
    if path and any(part in ('', '.', '..') for part in path.split('/')):
      raise ValueError('Location path cannot contain empty or traversal segments')
    return y2path(path)


class FileLocation(Location):
  """Files at the configured URI; naming rules belong to this implementation."""
  scheme = 'file'

  def __init__(self, properties: dict[str, Any], *, connection: dict[str, Any] | None = None,
               parent: Location | None = None, children: Callable[[], Iterable[Location]] | None = None,
               templates: dict[str, str] | None = None) -> None:
    super().__init__(properties, connection=connection, parent=parent, children=children)
    self.templates = deepcopy(templates)

  def _root(self) -> Path:
    uri = urlsplit(str(self.uri))
    if uri.scheme != 'file':
      raise ValueError('FileLocation requires a file URI')
    path = unquote(uri.path)
    if not path:
      raise ValueError(f'{self.uri}: select a child Location with a filesystem root')
    if len(path) >= 3 and path[0] == '/' and path[2] == ':':
      path = path[1:]
    if uri.netloc and uri.netloc.casefold() != socket.gethostname().split('.')[0].casefold():
      if os.name == 'nt' and not PureWindowsPath(path).drive:
        return Path('//' + uri.netloc + unquote(uri.path))
      raise ValueError(f'{self.uri}: file URI does not identify a file on this host')
    if len(path) == 2 and path[1] == ':':
      path += '/'
    root = Path(path)
    if not root.is_absolute():
      raise ValueError(f'{self.uri}: file Location requires an absolute filesystem root')
    return root

  def container(self, path: y2path | str = '') -> 'FileContainer':
    path = str(self.relative(path))
    root = self._root().resolve()
    target = (root / unquote(path)).resolve()
    if not target.is_relative_to(root):
      raise ValueError('Container must stay within its Location')
    return FileContainer(target, templates=self.templates, uri=self.address(path))

def _updated(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
  result = deepcopy(previous)
  for key, value in incoming.items():
    if key in result and isinstance(result[key], dict) and isinstance(value, dict):
      result[key] = _updated(result[key], value)
    else:
      result[key] = deepcopy(value)
  return result


class FileContainer(Container):
  """List, read, write and delete files using configured object path templates."""
  def __init__(self, root: str | Path, *, templates: dict[str, str] | None = None,
               uri: y2uri | str | None = None) -> None:
    root = Path(root)
    if not root.is_absolute():
      raise ValueError('File Container root must be absolute')
    self._root = root.resolve()
    self.root = self._root.as_posix()
    self.uri = y2uri(self._root.as_uri() if uri is None else uri)
    self.templates = None if templates is None else TemplateSet(named={'objects': deepcopy(templates)})
    self._known: dict[str, Path] | None = None
    self._held: dict[str, str] = {}

  def _object_file(self, path: y2path | str | DataObject) -> Path:
    """Resolve an object's own URI and metadata, or a path returned by ls."""
    if isinstance(path, DataObject):
      obj = path
      if self.templates is None:
        raise ValueError('File Container requires naming templates to resolve a DataObject')
      uri = urlsplit(str(obj.uri))
      context = dict(uri=obj.uri, endpoint=uri.path, tenant=uri.netloc, inside='.',
                     it=obj.content, unquote=unquote, identity=obj.identity, filename=obj.name, kind=obj.kind)
      if 'date' in self.templates.named:
        value = self.templates.render_template('date', it=obj.content, uri=obj.uri,
          parent=obj.parent.content if obj.parent is not None else None)
        context['date'] = datetime.fromisoformat(value) if value else None
      if obj.parent is not None:
        parent = self._object_file(obj.parent).relative_to(self._root).as_posix()
        path = self.templates.render_template(obj.kind, object_path=parent, parent=obj.parent.content, **context)
      else:
        path = self.templates.render_template('filename', **context)
      if not isinstance(path, str) or not path.strip():
        raise ValueError('Object filename template must return a nonempty relative path')
      context['path'] = path
      if 'identity' in self.templates.named:
        identity = self.templates.render_template('identity', **context)
        if identity is not None:
          if not isinstance(identity, str) or not identity:
            raise ValueError('Object identity template must return a nonempty string or None')
          if self._known is None:
            self._known = {}
            for saved in self._root.rglob('*.json'):
              saved_identity = self.templates.render_template('identity',
                **(context | {'it': json.loads(saved.read_bytes()),
                             'path': saved.relative_to(self._root).as_posix()}))
              if saved_identity is None:
                continue
              if saved_identity in self._known:
                raise ValueError(f'{saved}: duplicate saved object identity')
              self._known[saved_identity] = saved
              self._held[saved.relative_to(self._root).as_posix().casefold()] = saved_identity
          if identity in self._known:
            path = self._known[identity].relative_to(self._root).as_posix()
          else:
            original, number = path, 1
            attempted: set[str] = set()
            while path.casefold() in self._held:
              if path.casefold() in attempted:
                raise ValueError('Collision template must produce a new path')
              attempted.add(path.casefold())
              number += 1
              path = self.templates.render_template('collision', **(context | {'path': original, 'number': number}))
              if not isinstance(path, str) or not path.strip():
                raise ValueError('Collision template must return a nonempty relative path')
            self._known[identity] = self._object_file(path)
            self._held[path.casefold()] = identity
    if isinstance(path, y2path):
      path = str(path)
    if not isinstance(path, str):
      raise TypeError('Container requires a DataObject or a relative path')
    if '\\' in path or PureWindowsPath(path).drive or path.startswith('/') or '://' in path:
      raise ValueError('Container path must be relative with slash-separated segments')
    if '..' in path.split('/'):
      raise ValueError('Container path cannot escape its root')
    target = (self._root / path).resolve()
    if not target.is_relative_to(self._root):
      raise ValueError('Container path cannot escape its root')
    return target

  def ls(self, path: y2path | str = '', detail: bool = True) -> list[dict[str, Any]] | list[str]:
    rows = []
    for target in sorted(self._object_file(path).iterdir()):
      name = target.relative_to(self._root).as_posix()
      self._object_file(name)
      rows.append({'name': name, 'type': 'directory' if target.is_dir() else 'file',
                   'size': 0 if target.is_dir() else target.stat().st_size})
    return rows if detail else [row['name'] for row in rows]

  def walk(self, path: y2path | str = '', *, level: str = 'files', recursive: bool = False,
           boundaries: Iterable[y2path | str] = ()) -> Iterator[tuple[dict, list[dict]]]:
    from .indexing import walk_files
    path = str(Location.relative(path))
    self._object_file(path)
    yield from walk_files(self._root, path, level, recursive, boundaries)

  def read(self, path: y2path | str | DataObject) -> DataObject:
    target = self._object_file(path)
    binary = isinstance(path, DataObject) and (isinstance(path.content, bytes) or hasattr(path.content, 'read'))
    if target.suffix.casefold() == '.json' and not binary:
      content = json.loads(target.read_bytes())
    else:
      content = target.open('rb')
    if isinstance(path, DataObject):
      return replace(path, content=content, name=target.name)
    return DataObject(target.as_uri(), content, str(path), name=target.name)

  def write(self, obj: DataObject) -> None:
    if not isinstance(obj, DataObject):
      raise TypeError('Container.write requires a DataObject')
    target = self._object_file(obj)
    if target == self._root:
      raise ValueError('object template must name a file')
    target.parent.mkdir(parents=True, exist_ok=True)
    incoming = obj.content
    binary = isinstance(incoming, bytes) or hasattr(incoming, 'read')
    if not binary and target.exists() and 'identity' in self.templates.named:
      relative = target.relative_to(self._root).as_posix()
      identity = self.templates.render_template('identity', uri=obj.uri, it=incoming, path=relative)
      if identity is not None and identity != self.templates.render_template('identity',
          uri=obj.uri, it=json.loads(target.read_bytes()), path=relative):
        raise ValueError(f'{target}: refusing to replace a different object identity')
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
      if not binary:
        if target.exists() and filecmp.cmp(pending, target, shallow=False):
          return
        os.replace(pending, target)
      else:
        try:
          os.link(pending, target)
        except FileExistsError:
          if not filecmp.cmp(pending, target, shallow=False):
            raise FileExistsError(f'{target}: different content requires delete then write') from None
    finally:
      pending.unlink(missing_ok=True)

  def delete(self, path: y2path | str | DataObject) -> None:
    target = self._object_file(path)
    target.unlink()
    relative = target.relative_to(self._root).as_posix().casefold()
    if relative in self._held:
      identity = self._held.pop(relative)
      del self._known[identity]

  @contextmanager
  def _refresh(self, state: dict[str, Any], path: y2path | str) -> Iterator[tuple[Iterator[DataObject], Callable[[], None]]]:
    root = self._object_file(path)
    scope = root.as_uri()
    previous = state[scope] if scope in state else {}
    pending: dict[str, list[int]] = {}

    def objects() -> Iterator[DataObject]:
      targets = root.rglob('*') if root.is_dir() else [root]
      for target in targets:
        if target.is_dir() or target.suffix == '.pending':
          continue
        name = target.relative_to(self._root).as_posix()
        target = self._object_file(name)
        stat = target.stat()
        signature = [stat.st_mtime_ns, stat.st_size]
        if name not in previous or previous[name] != signature:
          obj = self.read(name)
          try:
            yield obj
          finally:
            if hasattr(obj.content, 'close'):
              obj.content.close()
        pending[name] = signature
      for name in previous.keys() - pending.keys():
        target = self._object_file(name)
        yield DataObject(target.as_uri(), b'', name, name=target.name, removed=True)

    def commit() -> None:
      state[scope] = pending

    yield objects(), commit
