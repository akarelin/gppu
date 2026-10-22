"""Read an existing gppufs SQLite index as a flat, read-only fsspec filesystem.

The index is the source of the listing, including for a copied or synced index.
Original relative paths are kept for byte reads; the index is never renamed.
"""
from __future__ import annotations

import io
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path, PurePosixPath

import fsspec
from fsspec import AbstractFileSystem

from .fs import GppuFileSystem
from .handlers import IGNORED


class GppuIndexedFileSystem(AbstractFileSystem):
    protocol = 'gppu-index'
    cachable = False

    def __init__(self, index: str | Path):
        super().__init__()
        self.index = Path(index)
        # A colocated index moves or syncs with its folder. A provenance-named
        # snapshot is only an index; its parent is not the original data root.
        self.source = GppuFileSystem(self.index.parent) if self.index.name.startswith('.') else None
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
            files, inside = fsspec.core.url_to_fs(f"{member}::{self.source.root.rstrip('/')}/{archive}")
            return io.BytesIO(files.cat_file(inside))   # whole: the archive closes when its filesystem goes
        return self.source.open(self.source.root.rstrip('/') + '/' + member, mode=mode, **kwargs)


def indexes(files: GppuFileSystem, folder: str):
    """Index paths immediately in folder; GppuIndexedFileSystem validates their tables."""
    try:
        rows = files.fs.ls(folder, detail=True)
    except PermissionError:
        return   # a folder this account cannot list holds no index it could read, as gppufs's _index_at says
    for row in rows:
        if row['type'] == 'file' and row['name'].endswith('.gppufs.sqlite'):
            yield Path(row['name'])
