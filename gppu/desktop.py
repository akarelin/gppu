"""A read-only Windows desktop view of gppufs, mounted through fsspec's FUSE bridge.

The mount has one named folder per configured source. All navigation and bytes
below those folders belong to gppufs. No handler parsing or index lives here.
"""
from __future__ import annotations

import os
import posixpath
from errno import EROFS
from pathlib import PurePosixPath

from fsspec import AbstractFileSystem

from .fs import GppuFileSystem
from .handlers import IGNORED
from .fs_index import GppuIndexedFileSystem, indexes


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
            if name.casefold() == 'indexed':
                raise ValueError('Indexed is the desktop index view')
        if len({name.casefold() for name in sources}) != len(sources):
            raise ValueError('desktop source names must be distinct on Windows')
        self.sources = dict(sources)
        self.indexed: dict[str, GppuIndexedFileSystem] = {}
        self._index_paths: set[str] = set()
        self._shown_as: dict[str, dict[str, str]] = {}   # a listed folder -> the names shown in it -> the names they stand for

    def _discover(self, fs, folder, name):
        if not fs.fs.isdir(folder):
            return
        for index in indexes(fs, folder):
            if index.as_posix().casefold() in self._index_paths:
                continue
            view = GppuIndexedFileSystem(index)
            stem = index.name.removeprefix('.').removesuffix('.gppufs.sqlite')
            label = name if name.split(' › ')[-1].casefold() == stem.casefold() else name + ' › ' + stem
            self.indexed[label] = view
            self._index_paths.add(view.index.as_posix().casefold())

    def _discover_roots(self):
        for name, fs in self.sources.items():
            self._discover(fs, fs.root, name)
            for row in fs.ls_sync(fs.root):   # gppufs's listing: an ignored folder, a junction or a link is not entered
                if row['gppu']['type'] == 'folder' and not set(row['gppu']['handlers']) & set(IGNORED):
                    child = PurePosixPath(row['gppu']['path'].replace('\\', '/')).name
                    self._discover(fs, posixpath.join(fs.root, child), name + ' › ' + child)

    def _index_view(self, parts):
        label = next((name for name in self.indexed if name.casefold() == parts[1].casefold()), None)
        if label is None:
            self._discover_roots()
            label = next((name for name in self.indexed if name.casefold() == parts[1].casefold()), None)
        if label is None:
            raise FileNotFoundError('/'.join(parts))
        return self.indexed[label], '/'.join(parts[2:])

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
        folder = posixpath.join(fs.root, *parts[1:-1])
        shown = self._shown_as.get(folder.casefold(), {})
        return fs, posixpath.join(folder, *([shown.get(parts[-1].casefold(), parts[-1])] if len(parts) > 1 else []))

    def _found(self, path):
        """The source of a path whose last name may be the one an entry is shown by: a folder not listed yet is listed
        first, since its listing says what each name shown in it stands for."""
        parts = self._parts(path)
        if len(parts) > 1:
            folder = '/' + '/'.join(parts[:-1])
            if self._source(folder)[1].casefold() not in self._shown_as:
                self.ls(folder, detail=False)
        return self._source(path)

    @staticmethod
    def _shown(row):
        """The name an entry is shown by: the one its handler gives it, as SessionHandler names a session by its start, its
        turns, its length and its topic, else its own."""
        return (row['gppu']['record'].get('data') or {}).get('normalized_name') or \
            PurePosixPath(row['gppu']['path'].replace('\\', '/')).name

    @staticmethod
    def _seconds(row, name):
        """The row as Windows is given it: its times in seconds, as gppufs reads a row's time. An archive member's index row
        holds it as text, which fusepy cannot give Windows, and Windows leaves out the entry. An entry whose handler read its
        span, such as a session, is created at its start and modified at its end, so Windows' date columns show its span."""
        span = GppuFileSystem._span(row.get('gppu', {}).get('record', {}).get('span'))   # an older index's row has no gppu
        modified = span.end if span else GppuFileSystem._modified(row)
        created = span.start.timestamp() if span else row.get('created')
        result = {key: value for key, value in row.items() if key not in ('mtime', 'created')} | {'name': name}
        return result | ({'mtime': modified.timestamp()} if modified else {}) | (
            {'ctime': created} if isinstance(created, (int, float)) else {})

    @classmethod
    def _row(cls, row, name):
        # Archive bytes are files to fsspec, but gppufs declares them navigable.
        result = cls._seconds(row, name)
        if row['gppu']['is_container']:
            result.update(type='directory', size=0)
        return result

    def info(self, path='', **kwargs):
        if not self._parts(path):
            return {'name': '/', 'type': 'directory', 'size': 0}
        parts = self._parts(path)
        if parts[0].casefold() == 'indexed':
            if len(parts) == 1:
                return {'name': '/Indexed', 'type': 'directory', 'size': 0}
            fs, relative = self._index_view(parts)
            return self._seconds(fs.info(relative), '/' + '/'.join(parts))
        fs, source = self._found(path)
        return self._row(fs.info_sync(source), '/' + '/'.join(parts))

    def ls(self, path='', detail=True, **kwargs):
        if not self._parts(path):
            rows = [self.info('/' + name) for name in self.sources] + [self.info('/Indexed')]
        elif self._parts(path)[0].casefold() == 'indexed':
            parts = self._parts(path)
            if len(parts) == 1:
                self._discover_roots()
                rows = [self.info('/Indexed/' + name) for name in self.indexed]
            else:
                fs, relative = self._index_view(parts)
                if not detail:   # names alone, as Windows asks a listing: no row's metadata is read for it
                    return ['/Indexed/' + parts[1] + name for name in fs.ls(relative, detail=False)]
                rows = [self._seconds(row, '/Indexed/' + parts[1] + row['name']) for row in fs.ls(relative)]
        else:
            fs, source = self._source(path)
            self._discover(fs, source, ' › '.join(self._parts(path)))
            listed = [row for row in fs.ls_sync(source)
                      if fs.fs._strip_protocol(row['gppu']['path']).replace('\\', '/').casefold() not in self._index_paths]
            self._shown_as[source.casefold()] = {self._shown(row).casefold(): PurePosixPath(row['gppu']['path'].replace('\\', '/')).name
                                                 for row in listed}
            here = PurePosixPath('/' + '/'.join(self._parts(path)))
            rows = [self._row(row, str(here / self._shown(row))) for row in listed]
        names = [row['name'].casefold() for row in rows]
        if len(names) != len(set(names)):
            raise ValueError(f'{path}: gppufs names collide in the Windows namespace')
        return rows if detail else [row['name'] for row in rows]

    def _open(self, path, mode='rb', **kwargs):
        if mode != 'rb':
            raise OSError(EROFS, 'desktop browsing is read-only', path)
        parts = self._parts(path)
        if parts[0].casefold() == 'indexed':
            fs, relative = self._index_view(parts)
            return fs.open(relative, mode=mode, **kwargs)
        fs, source = self._found(path)
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
