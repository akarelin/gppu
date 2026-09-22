"""The file Provider: a root or a configured folder on this host."""
from pathlib import Path
import socket

from fsspec.implementations.local import LocalFileSystem


class File:
  uid = 'file'
  schemas = {'local': 'file:///{path}', 'host': 'file://{host}/{path}'}

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
