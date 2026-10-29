r"""The virtual filesystem: gppufs read through fsspec as a read-only Windows drive.

A read-only Windows desktop view of gppufs, mounted through fsspec's FUSE bridge.

The mount has one named folder per configured source. All navigation and bytes
below a gppufs source's folder belong to gppufs; a source served by an API, such
as the catalog (gppu.fs.catalog), is an fsspec filesystem shown with its own names
and rows. What is shown is the index: a folder its handler says keeps its things
partitioned by date, such as Projects and Work, shows the things, each once by its
own name. No handler parsing or index lives here.

GppuIndexedFileSystem: Read an existing gppufs SQLite index as a flat, read-only fsspec filesystem.

The index is the source of the listing, including for a copied or synced index.
Original relative paths are kept for byte reads; the index is never renamed.
"""
from __future__ import annotations

import io
import json
import os
import posixpath
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from errno import EROFS
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import fsspec
from fsspec import AbstractFileSystem

from . import _modified, handlers
from .gppufs import GppuFileSystem
from .handlers import IGNORED


class GppuIndexedFileSystem(AbstractFileSystem):
    protocol = 'gppu-index'
    cachable = False

    def __init__(self, index: str | Path):
        super().__init__()
        self.index = Path(index)
        # A colocated index moves or syncs with its folder. A provenance-named
        # snapshot is only an index; its parent is not the original data root.
        self.source = GppuFileSystem() if self.index.name.startswith('.') else None
        self.root = self.index.parent.as_posix()   # the folder the index is beside, which its paths are below
        self._paths: dict[str, str] = {}  # display name -> original relative path; metadata stays in SQLite
        self._stamp, self._aliases = None, {}   # the index file's modified time and size when its names were read
        self._uri = self.index.as_uri()
        if self.index.anchor.startswith('\\\\'):
            self._uri = self._uri.replace('file://', 'file:////', 1)
        with self.database() as database:
            database.execute('SELECT path, metadata, children FROM gppufs_entries LIMIT 0')

    def database(self):
        """The index, opened for one read and closed after it: gppufs replaces an index whole, and Windows refuses to
        replace a file another process holds open."""
        return closing(sqlite3.connect(self._uri + '?mode=ro', uri=True))

    def _names(self, database):
        stamp = self.index.stat()
        if (stamp.st_mtime_ns, stamp.st_size) == self._stamp:   # the index has not changed since its names were read
            return self._aliases
        # what the handlers call ignored is not listed, as gppufs lists it nowhere; an index written before that still holds it
        paths = [path for path, handlers in database.execute(
            "SELECT path, json_extract(metadata, '$.gppu.handlers') FROM gppufs_entries"
            " WHERE json_extract(metadata, '$.type') = 'file' ORDER BY path")
            if not set(json.loads(handlers or '[]')) & set(IGNORED)]
        paths = [path for path in paths if not path.endswith(('.gppufs.sqlite', '.gppufs.sqlite-wal', '.gppufs.sqlite-shm'))]
        parts = {path: self._parts(path) for path in paths}
        # a file is named by the fewest folders nearest it that tell it apart from every other, ignoring case as Windows does
        named, pending, depth = {}, paths, 1
        while pending:
            tails = Counter(tuple(part.casefold() for part in parts[path][-depth:]) for path in pending)
            rest = []
            for path in pending:
                if depth >= len(parts[path]) or tails[tuple(part.casefold() for part in parts[path][-depth:])] == 1:
                    named[path] = ' › '.join(parts[path][-depth:])
                else:
                    rest.append(path)
            pending, depth = rest, depth + 1
        aliases = {}
        for path in paths:
            name = named[path]
            if len(name) > 255:   # a Windows name holds 255 characters: the end nearest the file is kept
                name = '…' + name[-254:]
            if name.casefold() in aliases:
                raise ValueError(f'{self.index}: indexed names collide on Windows: {name}')
            aliases[name.casefold()] = (name, path)
        self._paths = {key: path for key, (_, path) in aliases.items()}
        self._stamp, self._aliases = (stamp.st_mtime_ns, stamp.st_size), aliases
        return aliases

    def _parts(self, path):
        """The names an index path takes below its location. A member of an archive, which fsspec chains as
        protocol://member::archive, is the archive's names and then the member's, so no name holds the chain's colons."""
        member, _, archive = path.partition('::')
        relative = PurePosixPath(archive or path)
        if relative.is_absolute() or '..' in relative.parts or (not archive and '://' in path):
            raise ValueError(f'{self.index}: index path is not relative: {path}')
        return relative.parts + (PurePosixPath(member.partition('://')[2]).parts if archive else ())

    def _metadata(self, database, path, name):
        found = database.execute('SELECT metadata FROM gppufs_entries WHERE path=?', (path,)).fetchone()
        if found is None:
            raise FileNotFoundError(path)
        row = json.loads(found[0])
        return dict(row, name=name, type='file')

    def _relative(self, path):
        name = str(path).strip('/')
        if '/' in name or '\\' in name:
            raise FileNotFoundError(path)
        if name.casefold() not in self._paths:
            with self.database() as database:
                self._names(database)
        try:
            return self._paths[name.casefold()]
        except KeyError:
            raise FileNotFoundError(path) from None

    def info(self, path='', **kwargs):
        if not str(path).strip('/'):
            return {'name': '/', 'type': 'directory', 'size': 0}
        relative = self._relative(path)
        with self.database() as database:
            return self._metadata(database, relative, str(path))

    def ls(self, path='', detail=True, **kwargs):
        if str(path).strip('/'):
            row = self.info(path)
            return [row] if detail else [row['name']]
        with self.database() as database:
            names = self._names(database)
            if not detail:
                return ['/' + name for name, _ in names.values()]
            return [self._metadata(database, relative, '/' + name) for name, relative in names.values()]

    def _open(self, path, mode='rb', **kwargs):
        if mode != 'rb':
            raise PermissionError('an indexed view is read-only')
        if self.source is None:
            raise FileNotFoundError(f'{self.index}: this index snapshot has no bound original source for {path}')
        member, _, archive = self._relative(path).partition('::')
        if archive:   # the member, read from its archive in the location; an archive that is not there is not found
            files, inside = fsspec.core.url_to_fs(f"{member}::{self.root.rstrip('/')}/{archive}")
            return io.BytesIO(files.cat_file(inside))   # whole: the archive closes when its filesystem goes
        return self.source.open(self.root.rstrip('/') + '/' + member, mode=mode, **kwargs)


def indexes(files: GppuFileSystem, folder: str):
    """Index paths immediately in folder; GppuIndexedFileSystem validates their tables."""
    try:
        rows = files.fs.ls(folder, detail=True)
    except PermissionError:
        return   # a folder this account cannot list holds no index it could read, as gppufs's _index_at says
    for row in rows:
        if row['type'] == 'file' and row['name'].endswith('.gppufs.sqlite'):
            yield Path(row['name'])


class Thing(NamedTuple):
    """One thing a partitioned folder holds, its handler's, in each place it is kept: a task's folder on each day it has
    one, and its archived stages."""
    handler: type[handlers.PartitionedFolderHandler]
    places: list[str]


class DesktopFileSystem(AbstractFileSystem):
    """Project named sources into one ordinary filesystem namespace: a source is the address of a folder gppufs lists,
    `gppu::D:/TextLake`, or a filesystem served by an API, whose paths are its own."""

    protocol = 'gppu-desktop'
    cachable = False

    def __init__(self, sources: dict[str, str | AbstractFileSystem]):
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
        self.sources = {name: fsspec.core.url_to_fs(source) if isinstance(source, str) else (source, '')
                        for name, source in sources.items()}   # each its filesystem and the folder shown
        self.indexed: dict[str, GppuIndexedFileSystem] = {}
        self._index_paths: set[str] = set()
        # a listed folder, as shown -> each name shown in it -> the real path it stands for, or the thing it is
        self._shown_as: dict[str, dict[str, str | Thing]] = {}
        self._rows: dict[str, dict] = {}   # an entry a partitioned folder or a thing shows, as shown -> its row as listed

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
        for name, (fs, root) in self.sources.items():
            if not isinstance(fs, GppuFileSystem):
                continue
            self._discover(fs, root, name)
            for row in fs.ls_sync(root):   # gppufs's listing: an ignored folder, a junction or a link is not entered
                if row['gppu']['type'] == 'folder' and not set(row['gppu']['handlers']) & set(IGNORED):
                    child = PurePosixPath(row['gppu']['path'].replace('\\', '/')).name
                    self._discover(fs, posixpath.join(root, child), name + ' › ' + child)

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

    def _real(self, path):
        """The source of a shown path and what it stands for: a real folder or file, or a thing a partitioned folder holds. A
        name shown in a folder is what that folder's listing says it stands for, the folder listed first when it was not yet; a
        name the listing did not show, as one gppufs leaves out, is taken as it is."""
        parts = self._parts(path)
        name = next((name for name in self.sources if name.casefold() == parts[0].casefold()), None)
        if name is None:
            raise FileNotFoundError(path)
        fs, root = self.sources[name]
        if not isinstance(fs, GppuFileSystem):   # a source served by an API: its paths are its own
            return fs, '/'.join(parts[1:])
        if len(parts) == 1:
            return fs, root
        folder = '/' + '/'.join(parts[:-1])
        if folder.casefold() not in self._shown_as:
            self.ls(folder, detail=False)
        if (real := self._shown_as[folder.casefold()].get(parts[-1].casefold())) is not None:
            return fs, real
        if isinstance(parent := self._real(folder)[1], Thing):
            raise FileNotFoundError(path)
        return fs, posixpath.join(parent, parts[-1])

    def _held(self, fs, folder):
        """What the index holds in a real folder, each row with its real path, what gppufs ignores and the indexes the Indexed
        view shows left out: answered from the index alone once it holds the folder's listing, and the folder read, and so
        indexed, only while it does not."""
        stored = fs.stored(folder)
        return [(row, posixpath.join(folder, self._name(row))) for row in fs.ls_sync(folder, live=stored is None or stored[1] is None)
                if 'ignored' not in row['gppu']['handlers']
                and fs.fs._strip_protocol(row['gppu']['path']).replace('\\', '/').casefold() not in self._index_paths]

    @staticmethod
    def _name(row):
        return PurePosixPath(row['gppu']['path'].replace('\\', '/')).name

    def _handler(self, fs, folder):
        """The handler the index says reads a real folder."""
        return handlers.HANDLERS.get(fs.info_sync(folder)['gppu']['record']['type'])

    def _things(self, fs, folder, handler, level=0):
        """What a partitioned folder holds: in place of a partition, what the partition holds."""
        for row, place in self._held(fs, folder):
            if row['gppu']['type'] == 'folder' and handler.partition(self._name(row), level):
                yield from self._things(fs, place, handler, level + 1)
            else:
                yield row, place

    def _listed(self, fs, real, here):
        """The rows shown in a gppufs folder, as here, and what each name shown stands for: what the index holds there. A
        folder its handler says is partitioned shows the things its partitions hold, and a thing shows what it holds in each
        place it is kept; in both, an entry is shown once by its own name, a container being a thing and a file kept in several
        places being shown as its latest. Any other folder shows what it holds."""
        if isinstance(real, Thing):
            handler, held = real.handler, [entry for place in real.places for entry in self._held(fs, place)]
            spans = [(place, fs.spans(place, 1)) for place in real.places]
        else:
            self._discover(fs, real, ' › '.join(here.parts[1:]))
            handler = self._handler(fs, real)
            if not (handler and issubclass(handler, handlers.PartitionedFolderHandler)):
                held = self._held(fs, real)
                return ([self._row(row, str(here / self._shown(row))) for row, _ in held],
                        {self._shown(row).casefold(): place for row, place in held})
            held = list(self._things(fs, real, handler))
            spans = [(real, fs.spans(real, len(handler.partitions) + 1))]
        alike = defaultdict(list)
        for row, place in held:
            alike[self._own(row, handler).casefold(), row['gppu']['is_container']].append((row, place))
        shown_as, rows = {}, []
        for (_, container), kept in alike.items():
            if container:
                name = self._own(kept[0][0], handler)
                shown_as[name.casefold()] = Thing(handler, [place for _, place in kept])
                rows.append({'name': str(here / name), 'type': 'directory', 'size': 0} | self._spanned(kept, spans))
            else:
                row, place = max(kept, key=lambda entry: self._seconds(entry[0], '').get('mtime', 0))
                name = (row['gppu'].get('record') or {}).get('data', {}).get('normalized_name') or self._own(row, handler)
                shown_as[name.casefold()] = place
                rows.append(self._row(row, str(here / name)))
            self._rows[rows[-1]['name'].casefold()] = rows[-1]
        return rows, shown_as

    def _spanned(self, kept, spans):
        """A thing's span as the times Windows shows: from the first to the last modified time of the files the index holds
        below the places it is kept, each folder's spans as gppufs aggregates them; the folders' own times when it holds none."""
        found = [span for place in (place for _, place in kept) for folder, held in spans for prefix, span in held.items()
                 if prefix == (below := posixpath.relpath(place, folder)) or prefix.startswith(below + '/')]
        if found:
            return {'ctime': min(span.start for span in found).timestamp(), 'mtime': max(span.end for span in found).timestamp()}
        times = [self._seconds(row, '') for row, _ in kept]
        return {key: pick(row[key] for row in times if key in row) for key, pick in (('ctime', min), ('mtime', max))
                if any(key in row for row in times)}

    def _own(self, row, handler):
        """An entry's own name, as its partitioned folder's handler says it."""
        return handler.own_name(self._name(row), 'archive' in row['gppu']['handlers'])

    @staticmethod
    def _shown(row):
        """The name an entry is shown by: the one its handler gives it, as SessionHandler names a session by its start, its
        turns, its length and its topic, else its own, as for an entry no handler read."""
        return ((row['gppu'].get('record') or {}).get('data') or {}).get('normalized_name') or \
            PurePosixPath(row['gppu']['path'].replace('\\', '/')).name

    @staticmethod
    def _seconds(row, name):
        """The row as Windows is given it: its times in seconds, as gppufs reads a row's time. An archive member's index row
        holds it as text, which fusepy cannot give Windows, and Windows leaves out the entry. An entry whose handler read its
        span, such as a session, is created at its start and modified at its end, so Windows' date columns show its span."""
        span = GppuFileSystem._span(row.get('gppu', {}).get('record', {}).get('span'))   # an older index's row has no gppu
        modified = span.end if span else _modified(row)
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
        fs, real = self._real(path)
        if not isinstance(fs, GppuFileSystem):
            return fs.info(real) | {'name': '/' + '/'.join(parts)}
        if (listed := self._rows.get(('/' + '/'.join(parts)).casefold())) is not None:   # as the folder's listing showed it
            return listed | {'name': '/' + '/'.join(parts)}
        return self._row(fs.info_sync(real), '/' + '/'.join(parts))

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
        elif not isinstance((found := self._real(path))[0], GppuFileSystem):
            fs, real = found
            here = '/' + self._parts(path)[0]
            rows = [row | {'name': posixpath.join(here, row['name'])} for row in fs.ls(real)]
        else:
            fs, real = found
            here = PurePosixPath('/' + '/'.join(self._parts(path)))
            rows, self._shown_as[str(here).casefold()] = self._listed(fs, real, here)
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
        fs, real = self._real(path)
        if isinstance(real, Thing):
            raise IsADirectoryError(path)
        return fs.open(real, mode=mode, **kwargs)


def mount(sources: dict[str, str | AbstractFileSystem], mount_point: str) -> None:
    """Mount in this process; WinFsp owns the Windows mount lifecycle."""
    from fsspec.fuse import FUSEr
    from fuse import FUSE, FuseOSError

    class ReadOnly(FUSEr):
        def getattr(self, path, fh=None):
            """fsspec's attributes, and the start of the entry's span as the time Windows shows it created, which fsspec's
            bridge does not give."""
            data = super().getattr(path, fh)
            if 'st_mode' in data and 'ctime' in (info := self.fs.info(''.join([self.root, path.lstrip('/')]).rstrip('/'))):
                data['st_birthtime'] = info['ctime']
            return data

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
