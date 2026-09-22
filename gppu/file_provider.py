"""The file Provider: a root or a configured folder on this host."""
from pathlib import Path
import socket
from datetime import datetime
from urllib.parse import unquote, urlsplit

from fsspec.implementations.local import LocalFileSystem
from gppu.gppu import TemplateSet


class File:
  uid = 'file'
  schemas = {'local': 'file:///{path}', 'host': 'file://{host}/{path}'}

  def object_path(self, obj, location):
    """The destination's templates decide where a Provider object is stored."""
    templates = TemplateSet(named={'storage_templates': location['storage']})
    uri = urlsplit(obj.uri)
    if obj.parent is not None:
      parent = self.object_path(obj.parent, location)
      return str(templates.render_template(obj.kind, object_path=parent, filename=obj.name, uri=obj.uri))
    value = templates.render_template('date', it=obj.content, uri=obj.uri)
    try:
      date = datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
      date = None
    return str(templates.render_template('filename', uri=obj.uri, endpoint=uri.path, tenant=uri.netloc,
                                        date=date, inside=location['path'], it=obj.content, unquote=unquote))

  def local(self, connection, path):
    if any('/' in part or '\\' in part for part in path):
      raise ValueError('file paths must keep separators between URI segments')
    root = '/'.join(path)
    if not path or not (len(path[0]) == 2 and path[0][1] == ':'):
      root = '/' + root
    fs = LocalFileSystem()
    fs.root = Path(root).as_posix()
    if not Path(fs.root).is_absolute():
      raise ValueError('file Location must be absolute on this host')
    return fs

  def host(self, connection, host, path):
    if host.casefold() != socket.gethostname().split('.')[0].casefold():
      raise ValueError(f'file://{host} must be opened on {host}')
    return self.local(connection, path)


def register(registry):
  registry.register(File())
