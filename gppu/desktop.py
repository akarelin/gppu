"""A read-only Windows desktop view of gppufs, mounted through fsspec's FUSE bridge.

The mount has one named folder per configured source. All navigation and bytes
below those folders belong to gppufs. No handler parsing or index lives here.
"""
from __future__ import annotations

import os
from errno import EROFS
from pathlib import PurePosixPath

from fsspec import AbstractFileSystem

from .fs import GppuFileSystem


class DesktopFileSystem(AbstractFileSystem):
    """Project named gppufs roots into one ordinary filesystem namespace."""

    protocol = 'gppu-desktop'
    cachable = False

    def __init__(self, sources: dict[str, GppuFileSystem]):
        super().__init__()
        if not sources:
            raise ValueError('desktop sources are required')
        for name in sources:
            if not name or name in ('.', '..') or any(c in name for c in '/\\:'):
                raise ValueError(f'{name!r}: source name must be one Windows folder name')
        if len({name.casefold() for name in sources}) != len(sources):
            raise ValueError('desktop source names must be distinct on Windows')
        self.sources = dict(sources)

    @staticmethod
    def _parts(path):
        parts = PurePosixPath(str(path).replace('\\', '/')).parts
        parts = tuple(part for part in parts if part != '/')
        if '..' in parts:
            raise ValueError('desktop paths cannot leave their source')
        return parts

    def _source(self, path):
        parts = self._parts(path)
        name = next((name for name in self.sources if name.casefold() == parts[0].casefold()), None)
        if name is None:
            raise FileNotFoundError(path)
        fs = self.sources[name]
        return fs, '/'.join((fs.root.rstrip('/'), *parts[1:]))

    @staticmethod
    def _row(row, name):
        # Archive bytes are files to fsspec, but gppufs declares them navigable.
        result = dict(row, name=name)
        if row['gppu']['is_container']:
            result.update(type='directory', size=0)
        return result

    def info(self, path='', **kwargs):
        if not self._parts(path):
            return {'name': '/', 'type': 'directory', 'size': 0}
        fs, source = self._source(path)
        return self._row(fs.info_sync(source), '/' + '/'.join(self._parts(path)))

    def ls(self, path='', detail=True, **kwargs):
        if not self._parts(path):
            rows = [self.info('/' + name) for name in self.sources]
        else:
            fs, source = self._source(path)
            rows = [self._row(row, str(PurePosixPath('/' + '/'.join(self._parts(path))) /
                    PurePosixPath(row['gppu']['path'].replace('\\', '/')).name))
                    for row in fs.ls_sync(source)]
        names = [row['name'].casefold() for row in rows]
        if len(names) != len(set(names)):
            raise ValueError(f'{path}: gppufs names collide in the Windows namespace')
        return rows if detail else [row['name'] for row in rows]

    def _open(self, path, mode='rb', **kwargs):
        if mode != 'rb':
            raise OSError(EROFS, 'desktop browsing is read-only', path)
        fs, source = self._source(path)
        return fs.open(source, mode=mode, **kwargs)


def mount(sources: dict[str, GppuFileSystem], mount_point: str) -> None:
    """Mount in this process; WinFsp owns the Windows mount lifecycle."""
    from fsspec.fuse import FUSEr
    from fuse import FUSE, FuseOSError

    class ReadOnly(FUSEr):
        def open(self, path, flags):
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                raise FuseOSError(EROFS)
            return super().open(path, flags)

        def release(self, path, fh):
            self.cache.pop(fh).close()
            return 0

        def readonly(self, *args, **kwargs):
            raise FuseOSError(EROFS)

        create = write = truncate = unlink = mkdir = rmdir = rename = chmod = chown = utimens = readonly

    FUSE(ReadOnly(DesktopFileSystem(sources), ''), mount_point,
         foreground=True, nothreads=True, ro=True, volname='gppufs')
