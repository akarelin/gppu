"""Locations select Containers; Containers exchange source-addressed data."""
import base64
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
from typing import Any, BinaryIO, TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit

from .gppu import TemplateSet, _Base

if TYPE_CHECKING:
  import msal
  import requests


@dataclass(frozen=True)
class DataObject:
  uri: str
  content: dict[str, Any] | list[Any] | str | int | float | bool | None | bytes | BinaryIO
  identity: str | None
  kind: str = 'object'
  name: str = ''
  parent: 'DataObject | None' = None
  removed: bool = False


class Container:
  """Operations below a Location boundary, with source-owned refresh state."""

  def ls(self, path: str = '', detail: bool = True) -> list[dict[str, Any]] | list[str]:
    """Immediate folders and objects in this Container, using fsspec entries."""
    raise NotImplementedError

  def read(self, path: str | DataObject) -> DataObject:
    """Read one object without changing a refresh cursor."""
    raise NotImplementedError

  def write(self, obj: DataObject) -> None:
    """Write the object's files."""
    raise NotImplementedError

  def delete(self, path: str | DataObject) -> None:
    """Explicitly remove an object before a deliberate replacement."""
    raise NotImplementedError

  def _refresh(self, state: dict[str, Any], path: str) -> AbstractContextManager[tuple[Iterator[DataObject], Callable[[], None]]]:
    """Yield objects and a callback updating the caller's refresh state."""
    raise NotImplementedError

  @contextmanager
  def refresh(self, state: dict[str, Any], path: str = '') -> Iterator[Iterator[DataObject]]:
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
    self.uri = properties['canonical']
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

  def container(self, path: str = '') -> Container:
    raise NotImplementedError(f'{self.uri}: Containers are not implemented')

  @staticmethod
  def relative(path: str) -> str:
    if not isinstance(path, str) or path.startswith('/') or '\\' in path or '://' in path:
      raise ValueError('Location path must be relative and slash-separated')
    if path and any(part in ('', '.', '..') for part in path.split('/')):
      raise ValueError('Location path cannot contain empty or traversal segments')
    return path


class FileLocation(Location):
  """Files at the configured URI; naming rules belong to this implementation."""
  scheme = 'file'

  def __init__(self, properties: dict[str, Any], *, connection: dict[str, Any] | None = None,
               parent: Location | None = None, children: Callable[[], Iterable[Location]] | None = None,
               templates: dict[str, str] | None = None) -> None:
    super().__init__(properties, connection=connection, parent=parent, children=children)
    self.templates = deepcopy(templates)

  def _root(self) -> Path:
    uri = urlsplit(self.uri)
    if uri.scheme != 'file':
      raise ValueError('FileLocation requires a file URI')
    if uri.netloc and uri.netloc.casefold() != socket.gethostname().split('.')[0].casefold():
      if os.name == 'nt':
        return Path('//' + uri.netloc + unquote(uri.path))
      raise ValueError(f'{self.uri}: file URI does not identify a file on this host')
    path = unquote(uri.path)
    if len(path) >= 3 and path[0] == '/' and path[2] == ':':
      path = path[1:]
    return Path(path)

  def container(self, path: str = '') -> 'FileContainer':
    self.relative(path)
    root = self._root().resolve()
    target = (root / unquote(path)).resolve()
    if not target.is_relative_to(root):
      raise ValueError('Container must stay within its Location')
    return FileContainer(target, templates=self.templates)

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
  def __init__(self, root: str | Path, *, templates: dict[str, str] | None = None) -> None:
    root = Path(root)
    if not root.is_absolute():
      raise ValueError('File Container root must be absolute')
    self._root = root.resolve()
    self.root = self._root.as_posix()
    self.templates = None if templates is None else TemplateSet(named={'objects': deepcopy(templates)})
    self._known: dict[str, Path] | None = None
    self._held: dict[str, str] = {}

  def _object_file(self, path: str | DataObject) -> Path:
    """Resolve an object's own URI and metadata, or a path returned by ls."""
    if isinstance(path, DataObject):
      obj = path
      if self.templates is None:
        raise ValueError('File Container requires naming templates to resolve a DataObject')
      uri = urlsplit(obj.uri)
      context = dict(uri=obj.uri, endpoint=uri.path, tenant=uri.netloc, inside='.',
                     it=obj.content, unquote=unquote, identity=obj.identity, filename=obj.name, kind=obj.kind)
      if 'date' in self.templates.named:
        value = self.templates.render_template('date', it=obj.content, uri=obj.uri,
          parent=obj.parent.content if obj.parent is not None else None)
        context['date'] = datetime.fromisoformat(value) if value else None
      if obj.parent is not None:
        parent = self._object_file(obj.parent).relative_to(self._root).as_posix()
        path = str(self.templates.render_template(obj.kind, object_path=parent, parent=obj.parent.content, **context))
      else:
        path = str(self.templates.render_template('filename', **context))
      if 'identity' in self.templates.named:
        identity = self.templates.render_template('identity', **context)
        if identity is not None:
          if not isinstance(identity, str) or not identity:
            raise ValueError('Object identity template must return a nonempty string or None')
          if self._known is None:
            self._known = {}
            for saved in self._root.rglob('*.json'):
              saved_identity = self.templates.render_template('identity',
                **(context | {'it': json.loads(saved.read_bytes())}))
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
            while path.casefold() in self._held:
              number += 1
              path = str(self.templates.render_template('collision', path=original, number=number, **context))
            self._known[identity] = self._object_file(path)
            self._held[path.casefold()] = identity
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

  def ls(self, path: str = '', detail: bool = True) -> list[dict[str, Any]] | list[str]:
    rows = []
    for target in sorted(self._object_file(path).iterdir()):
      name = target.relative_to(self._root).as_posix()
      self._object_file(name)
      rows.append({'name': name, 'type': 'directory' if target.is_dir() else 'file',
                   'size': 0 if target.is_dir() else target.stat().st_size})
    return rows if detail else [row['name'] for row in rows]

  def read(self, path: str | DataObject) -> DataObject:
    target = self._object_file(path)
    binary = isinstance(path, DataObject) and (isinstance(path.content, bytes) or hasattr(path.content, 'read'))
    if target.suffix.casefold() == '.json' and not binary:
      content = json.loads(target.read_bytes())
    else:
      content = target.open('rb')
    if isinstance(path, DataObject):
      return replace(path, content=content, name=target.name)
    return DataObject(target.as_uri(), content, path, name=target.name)

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
      identity = self.templates.render_template('identity', uri=obj.uri, it=incoming)
      if identity is not None and identity != self.templates.render_template('identity',
          uri=obj.uri, it=json.loads(target.read_bytes())):
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

  def delete(self, path: str | DataObject) -> None:
    target = self._object_file(path)
    target.unlink()
    relative = target.relative_to(self._root).as_posix().casefold()
    if relative in self._held:
      identity = self._held.pop(relative)
      del self._known[identity]

  @contextmanager
  def _refresh(self, state: dict[str, Any], path: str) -> Iterator[tuple[Iterator[DataObject], Callable[[], None]]]:
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

class M365Location(Location):
  scheme = 'm365'

  def __init__(self, properties: dict[str, object], *, connection: dict[str, object],
               parent: Location | None = None, children: Callable[[], Iterable[Location]] | None = None,
               credential_root: Path | None = None) -> None:
    super().__init__(properties, connection=connection, parent=parent, children=children)
    import requests
    self._session = parent._session if isinstance(parent, M365Location) and self._connection == parent._connection else requests.Session()
    self._app: 'msal.ConfidentialClientApplication | None' = None
    self._credential_root = credential_root
    uri = urlsplit(self.uri)
    if uri.scheme != self.scheme or not uri.netloc or uri.query or uri.fragment:
      raise ValueError('M365 Location requires an absolute m365 URI without query or fragment')
    self._namespace = 'm365://' + uri.netloc

  def ls(self) -> list[Location]:
    children = list(super().ls())
    configured = {child.uri for child in children}
    path = urlsplit(self.uri).path.strip('/')
    segments = tuple(unquote(segment) for segment in path.split('/')) if path else ()
    if not segments:
      rows = [('users', 'Users')]
    elif segments == ('users',):
      rows = [(quote(record['userPrincipalName'], safe='@'), record['displayName'])
              for record in self._each('/users')]
    elif len(segments) == 2 and segments[0] == 'users':
      rows = [('contacts', 'Contacts'), ('calendars', 'Calendars'),
              ('todo/lists', 'To Do'), ('onedrive', 'OneDrive')]
    else:
      rows = []
    for relative, name in rows:
      uri = self.uri.rstrip('/') + '/' + relative
      if uri in configured:
        continue
      properties = deepcopy(self._my)
      properties.update(uid=self.uid.rstrip('/') + '/' + relative, canonical=uri,
        name=name, path=unquote(urlsplit(uri).path.lstrip('/')), parent=self.uid)
      children.append(M365Location(properties, connection=self._connection, parent=self,
        credential_root=self._credential_root))
    return children

  def container(self, path: str = '') -> 'M365Container':
    self.relative(path)
    full = self.uri.rstrip('/') + ('/' + path if path else '')
    segments = tuple(unquote(segment) for segment in urlsplit(full).path.strip('/').split('/')) if urlsplit(full).path.strip('/') else ()
    if len(segments) >= 3 and segments[0] == 'users':
      user, branch, tail = segments[1], segments[2], segments[3:]
      if branch == 'todo':
        if not tail or tail[0] != 'lists':
          raise ValueError('To Do Containers start at todo/lists')
        tail = tail[1:]
    elif len(segments) >= 2 and segments[1] in ('onedrive', 'sharepoint'):
      user, branch, tail = segments[0], segments[1], segments[2:]
    else:
      raise ValueError('Select a user data Container within the M365 Location')
    if branch not in ('contacts', 'contactFolders', 'calendars', 'todo', 'onedrive', 'sharepoint'):
      raise ValueError(f'Unsupported M365 endpoint: {branch}')
    mailbox = self._connection['email'] if 'alias' in self._connection and user == self._connection['alias'] else user
    return M365Container(self, mailbox, branch, tail, self.uri.rstrip('/') + ('/' + path if path else ''))

  def _token(self) -> str:
    if isinstance(self.parent, M365Location) and self._connection == self.parent._connection:
      return self.parent._token()
    if self._app is None:
      import msal
      if self._credential_root is None:
        raise ValueError('M365 Location requires its configured credential root')
      from azure.identity import DefaultAzureCredential
      from azure.keyvault.secrets import SecretClient
      credential_file = Path(self._credential_root) / self._connection['app']
      identity = json.loads(credential_file.read_text(encoding='utf-8'))
      if 'client_secret' in identity:
        credential = identity['client_secret']
      else:
        reference = urlsplit(identity['certificate_password_ref'])
        if reference.scheme != 'azure-keyvault':
          raise ValueError('Certificate password must reference Azure Key Vault')
        vault = SecretClient('https://' + reference.netloc + '.vault.azure.net', DefaultAzureCredential())
        credential = {'private_key_pfx_path': str(credential_file.with_suffix('.pfx')),
                      'passphrase': vault.get_secret(reference.path.lstrip('/')).value}
      self._app = msal.ConfidentialClientApplication(identity['client_id'],
        authority='https://login.microsoftonline.com/' + identity['tenant_id'], client_credential=credential)
    result = self._app.acquire_token_for_client(scopes=[self._connection['scope']])
    if 'access_token' not in result:
      raise PermissionError(result)
    return result['access_token']

  def _request(self, url: str) -> 'requests.Response':
    api = self._connection['api'].rstrip('/')
    url = url if url.startswith('https://') else api + '/' + url.lstrip('/')
    parsed, configured = urlsplit(url), urlsplit(api)
    if parsed.scheme != 'https' or parsed.netloc != configured.netloc or parsed.username or parsed.password:
      raise ValueError('M365 API URL must stay on the configured Microsoft host')
    if '/events/delta' in parsed.path and not parsed.path.startswith('/beta/'):
      raise ValueError('Unbounded calendar delta requires the configured Microsoft Graph beta API')
    return self._session.get(url, headers={'Authorization': 'Bearer ' + self._token()}, timeout=60)

  def _get(self, url: str) -> dict[str, Any]:
    response = self._request(url)
    response.raise_for_status()
    return response.json()

  def _bytes(self, url: str) -> bytes | None:
    response = self._request(url)
    if response.status_code == 404:
      return None
    response.raise_for_status()
    return response.content

  def _each(self, url: str) -> Iterator[dict[str, Any]]:
    while True:
      page = self._get(url)
      yield from page['value']
      if '@odata.nextLink' not in page:
        break
      url = page['@odata.nextLink']


class M365Container(Container):
  """Folders and objects below an M365 Location; connection stays on the Location."""

  def __init__(self, location: M365Location, user: str, branch: str, path: tuple[str, ...], uri: str) -> None:
    self.location = location
    self.user, self._branch, self.path = user, branch, tuple(path)
    self.uri = uri
    self._user_path = '/users/' + quote(user, safe='')

  def _folder_url(self, segments: tuple[str, ...]) -> str:
    if self._branch in ('contacts', 'contactFolders'):
      return self._user_path + '/contactFolders/' + quote(segments[-1], safe='') if segments else self._user_path
    if self._branch in ('calendars', 'todo'):
      branch = 'calendars' if self._branch == 'calendars' else 'todo/lists'
      if len(segments) > 1:
        raise ValueError('Select one calendar or task list')
      return self._user_path + '/' + branch + ('/' + quote(segments[0], safe='') if segments else '')
    if self._branch == 'onedrive':
      return self._user_path + '/drive/' + ('items/' + quote(segments[-1], safe='') if segments else 'root')
    if self._branch == 'sharepoint':
      if len(segments) > 2:
        raise ValueError('Select a site or a list within the SharePoint Container')
      return '/sites/' + quote(segments[0], safe='') + ('/lists/' + quote(segments[1], safe='') if len(segments) == 2 else '') if segments else '/sites'
    raise ValueError(f'Unsupported M365 endpoint: {self._branch}')

  def _objects_url(self, segments: tuple[str, ...]) -> str | None:
    folder = self._folder_url(segments)
    if self._branch in ('contacts', 'contactFolders'):
      return folder + '/contacts'
    if self._branch in ('calendars', 'todo'):
      return folder + ('/events' if self._branch == 'calendars' else '/tasks') if segments else None
    if self._branch == 'onedrive':
      return folder + '/children'
    return folder + '/items' if len(segments) == 2 else None

  def _folders(self, segments: tuple[str, ...]) -> Iterator[dict[str, Any]]:
    folder = self._folder_url(segments)
    if self._branch in ('contacts', 'contactFolders'):
      url = folder + ('/childFolders' if segments else '/contactFolders')
    elif self._branch in ('calendars', 'todo'):
      if segments:
        return
      url = folder
    elif self._branch == 'sharepoint':
      if len(segments) == 2:
        return
      url = folder + ('/lists' if segments else '/getAllSites')
    else:
      url = folder + '/children'
    for record in self.location._each(url):
      if self._branch != 'onedrive' or 'folder' in record:
        yield record

  def ls(self, path: str = '', detail: bool = True) -> list[dict[str, object]] | list[str]:
    Location.relative(path)
    segments = self.path + tuple(unquote(segment) for segment in path.split('/')) if path else self.path
    rows = []
    def entry(record: dict[str, Any], kind: str) -> dict[str, object]:
      identity = record['id']
      name = '/'.join(part for part in (path, quote(identity, safe='')) if part)
      return {'name': name, 'type': kind, 'size': 0, 'gppu': {'record': record}}
    if self._branch == 'onedrive':
      rows = [entry(record, 'directory' if 'folder' in record else 'file')
              for record in self.location._each(self._objects_url(segments))]
    else:
      rows.extend(entry(record, 'directory') for record in self._folders(segments))
      url = self._objects_url(segments)
      if url is not None:
        rows.extend(entry(record, 'file') for record in self.location._each(url))
    return rows if detail else [row['name'] for row in rows]

  def _object(self, endpoint: str, record: dict[str, Any], parent: DataObject | None = None) -> DataObject:
    return DataObject(self.location._namespace + endpoint, record, record['id'],
                      parent=parent, removed='@removed' in record or 'deleted' in record)

  def read(self, path: str) -> DataObject:
    if not path:
      raise IsADirectoryError(self.uri)
    folder, _, identity = path.rpartition('/')
    Location.relative(path)
    segments = self.path + tuple(unquote(segment) for segment in folder.split('/')) if folder else self.path
    if self._branch == 'onedrive':
      url = self._folder_url((*segments, unquote(identity)))
    else:
      endpoint = self._objects_url(segments)
      if endpoint is None:
        raise IsADirectoryError(path)
      url = endpoint + '/' + quote(unquote(identity), safe='')
    read_url = self._user_path + '/events/' + quote(unquote(identity), safe='') if self._branch == 'calendars' else url
    parent = None
    if self._branch in ('contacts', 'contactFolders', 'calendars', 'todo'):
      for index in range(len(segments)):
        folder_url = self._folder_url(segments[:index + 1])
        parent = self._object(folder_url, self.location._get(folder_url), parent)
    return self._object(url, self.location._get(read_url), parent)

  def write(self, obj: DataObject) -> None:
    raise PermissionError('M365 source Containers are read-only')

  def delete(self, path: str | DataObject) -> None:
    raise PermissionError('M365 source Containers are read-only')

  def _endpoints(self, segments: tuple[str, ...], seen: set[str],
                 record: dict[str, Any] | None = None,
                 parent: DataObject | None = None) -> Iterator[tuple[str, DataObject | None]]:
    folder = self._folder_url(segments)
    if folder in seen:
      return
    seen.add(folder)
    if record is not None:
      parent = self._object(folder, record, parent)
      yield folder, parent
    endpoint = self._objects_url(segments)
    # Contacts delta is folder-scoped. contactFolders includes the native default
    # Contacts folder; /users/{id}/contacts/delta is not supported by Graph.
    if endpoint is not None and not (self._branch in ('contacts', 'contactFolders') and not segments):
      yield endpoint, None
    for record in self._folders(segments):
      yield from self._endpoints((*segments, record['id']), seen, record, parent)

  def _children(self, endpoint: str, obj: DataObject) -> Iterator[DataObject]:
    if obj.removed:
      return
    if self._branch == 'onedrive' and 'file' in obj.content:
      response = self.location._request(endpoint + '/content')
      response.raise_for_status()
      yield DataObject(obj.uri + '/content', response.content, obj.identity,
                       kind='file', name=obj.content['name'], parent=obj)
    if self._branch in ('contacts', 'contactFolders'):
      photo = self.location._bytes(endpoint + '/photo/$value')
      if photo is not None:
        yield DataObject(obj.uri + '/photo/$value', photo, None, kind='photo', parent=obj)
    if self._branch in ('calendars', 'todo') and obj.content.get('hasAttachments'):
      for attachment in self.location._each(endpoint + '/attachments'):
        if 'contentBytes' in attachment:
          yield DataObject(obj.uri + '/attachments/' + quote(attachment['id'], safe=''),
            base64.b64decode(attachment['contentBytes'], validate=True), attachment['id'],
            kind='attachment', name=attachment['name'], parent=obj)
        else:
          yield DataObject(obj.uri + '/attachments/' + quote(attachment['id'], safe=''), attachment,
                           attachment['id'], kind='attachment', name=attachment['name'], parent=obj)
    if self._branch == 'todo':
      for relation in ('checklistItems', 'linkedResources'):
        for child in self.location._each(endpoint + '/' + relation):
          identity = child['externalId'] if relation == 'linkedResources' and child.get('externalId') else child['id']
          yield DataObject(obj.uri + '/' + relation + '/' + quote(identity, safe=''), child, identity, parent=obj)

  @contextmanager
  def _refresh(self, state: dict[str, Any], path: str) -> Iterator[tuple[Iterator[DataObject], Callable[[], None]]]:
    Location.relative(path)
    segments = self.path + tuple(unquote(segment) for segment in path.split('/')) if path else self.path
    scope = self.uri.rstrip('/') + ('/' + path if path else '')
    pending = deepcopy(state[scope]) if scope in state else {}
    def commit() -> None:
      state[scope] = pending
    def objects() -> Iterator[DataObject]:
      if self._branch == 'onedrive' and segments:
        raise NotImplementedError('OneDrive delta refresh is supported at the drive root')
      endpoints: Iterable[tuple[str, DataObject | None]]
      if self._branch == 'onedrive':
        endpoints = [(self._folder_url(segments), None)]
      else:
        folder = self.location._get(self._folder_url(segments)) if segments else None
        endpoints = self._endpoints(segments, set(), folder)
      parent = None
      for endpoint, folder in endpoints:
        if folder is not None:
          parent = folder
          if endpoint not in pending or pending[endpoint] != folder.content:
            pending[endpoint] = deepcopy(folder.content)
            yield folder
          continue
        held = pending[endpoint] if endpoint in pending else {'objects': {}}
        url = held['delta'] if 'delta' in held else endpoint + '/delta'
        if 'delta' not in held and self._branch == 'sharepoint':
          url += '?$expand=fields'
        while True:
          page = self.location._get(url)
          for record in page['value']:
            identity = record['id']
            object_url = endpoint + '/' + quote(identity, safe='')
            if self._branch == 'onedrive':
              object_url = self._user_path + '/drive/items/' + quote(identity, safe='')
            removed = '@removed' in record or 'deleted' in record
            read_url = self._user_path + '/events/' + quote(identity, safe='') if self._branch == 'calendars' else object_url
            # Unbounded event delta returns only identity, type, start and end.
            # Read the complete changed event before yielding or advancing state.
            if self._branch == 'calendars' and not removed:
              content = self.location._get(read_url)
            else:
              content = _updated(held['objects'][identity], record) if identity in held['objects'] else deepcopy(record)
            if not removed:
              content.pop('@removed', None)
              content.pop('deleted', None)
            held['objects'][identity] = deepcopy(content)
            obj = self._object(object_url, content, parent)
            yield obj
            yield from self._children(read_url, obj)
          if '@odata.nextLink' in page:
            url = page['@odata.nextLink']
          else:
            held['delta'] = page['@odata.deltaLink']
            pending[endpoint] = held
            break
    yield objects(), commit
