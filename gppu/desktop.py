"""A read-only Windows desktop view of gppufs, mounted through fsspec's FUSE bridge.

The mount has one named folder per configured source. All navigation and bytes
below a gppufs source's folder belong to gppufs; a source served by an API, such
as the catalog (gppu.catalog), is an fsspec filesystem shown with its own names
and rows. A folder stored partitioned by date, such as Projects and Work, is shown
flattened, what its partitions hold correctly grouped. No handler parsing or index
lives here.
"""
from __future__ import annotations

import os
import posixpath
import re
from collections import Counter, defaultdict
from errno import EROFS
from pathlib import PurePosixPath

from fsspec import AbstractFileSystem

from .fs import GppuFileSystem
from .handlers import IGNORED
from .fs_index import GppuIndexedFileSystem, indexes

MONTH = re.compile(r'0[1-9]|1[0-2]')   # a month partition's name, MM
DAY = re.compile(r'0[1-9]|[12][0-9]|3[01]')   # a day partition's name in a month, DD
# A date leading a name as the Lake's layout writes one (CRAP Systems/lake/docs/layout.md), then its separator: YYMMDD, YYMMDD.HHMM,
# YYMMDD.HHMMSS, YYMMDD-HHMM or YYMMDD HHMM, its month the second pair; or YYYY-MM
DATED = re.compile(r'\d{2}(\d{2})\d{2}(?:[.-]\d{4}(?:\d{2})?| \d{4})?[ -]|\d{4}-(\d{2})[ -]')


class DesktopFileSystem(AbstractFileSystem):
    """Project named gppufs roots into one ordinary filesystem namespace."""

    protocol = 'gppu-desktop'
    cachable = False

    def __init__(self, sources: dict[str, AbstractFileSystem]):
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
        # a listed folder, as shown -> each name shown in it -> the real path it stands for, or, for a folder grouping one thing
        # the date partitions hold, each folder it groups with the partition that folder is in
        self._shown_as: dict[str, dict[str, str | list[tuple[str, str]]]] = {}
        self._groups: dict[str, dict] = {}   # a grouping folder, as shown -> its row

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
            if not isinstance(fs, GppuFileSystem):
                continue
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

    def _real(self, path):
        """The source of a shown path and what it stands for: a real folder or file, or, for a folder grouping one thing the
        date partitions hold, each folder it groups with its partition. A name shown in a folder is what that folder's listing
        says it stands for, the folder listed first when it was not yet; a name the listing did not show, as one gppufs leaves
        out, is taken as it is."""
        parts = self._parts(path)
        name = next((name for name in self.sources if name.casefold() == parts[0].casefold()), None)
        if name is None:
            raise FileNotFoundError(path)
        fs = self.sources[name]
        if not isinstance(fs, GppuFileSystem):   # a source served by an API: its paths are its own
            return fs, '/'.join(parts[1:])
        if len(parts) == 1:
            return fs, fs.root
        folder = '/' + '/'.join(parts[:-1])
        if folder.casefold() not in self._shown_as:
            self.ls(folder, detail=False)
        if (real := self._shown_as[folder.casefold()].get(parts[-1].casefold())) is not None:
            return fs, real
        if isinstance(parent := self._real(folder)[1], list):
            raise FileNotFoundError(path)
        return fs, posixpath.join(parent, parts[-1])

    def _held(self, fs, folder):
        """What gppufs lists in a real folder, each row with its real path, without the indexes the Indexed view shows."""
        return [(row, posixpath.join(folder, self._name(row))) for row in fs.ls_sync(folder)
                if fs.fs._strip_protocol(row['gppu']['path']).replace('\\', '/').casefold() not in self._index_paths]

    @staticmethod
    def _name(row):
        return PurePosixPath(row['gppu']['path'].replace('\\', '/')).name

    @staticmethod
    def _of_month(row, month):
        """Whether an entry belongs in a month partition: a day folder, or named with a date of that month."""
        name = DesktopFileSystem._name(row)
        if row['gppu']['type'] == 'folder' and DAY.fullmatch(name):
            return True
        return (dated := DATED.match(name)) is not None and month in dated.groups()

    def _flattened(self, fs, held):
        """A folder's entries with its date partitions flattened, each with the partition it is in: a month folder, MM, whose
        every entry is a day folder, DD, or is named with a date of that month, is replaced by what it holds, and a day folder
        in it by what that holds; anything else is in none."""
        for row, real in held:
            month = self._name(row)
            inside = self._held(fs, real) if row['gppu']['type'] == 'folder' and MONTH.fullmatch(month) else None
            if not inside or not all(self._of_month(entry, month) for entry, _ in inside):
                yield row, real, ''
                continue
            for entry, place in inside:
                day = self._name(entry)
                if entry['gppu']['type'] == 'folder' and DAY.fullmatch(day):
                    yield from ((inner, there, f'{month}-{day}') for inner, there in self._held(fs, place))
                else:
                    yield entry, place, month

    @staticmethod
    def _key(name):
        """A name with the date leading it set aside: what one thing is called in each partition holding it."""
        return name[dated.end():] if (dated := DATED.match(name)) else name

    def _group(self, members, name):
        """The row of a folder grouping one thing the partitions hold: created when the earliest was, modified when the latest
        was."""
        rows = [self._seconds(row, name) for row, _, _ in members]
        times = {key: [row[key] for row in rows if key in row] for key in ('ctime', 'mtime')}
        return {'name': name, 'type': 'directory', 'size': 0} | ({'ctime': min(times['ctime'])} if times['ctime'] else {}) | (
            {'mtime': max(times['mtime'])} if times['mtime'] else {})

    def _listed(self, fs, real, here):
        """The rows shown in a gppufs folder, as here, and what each name shown stands for. A folder grouping one thing the
        partitions hold shows what each folder it groups holds, a name two of them hold led by the partition it is in; a folder
        stored partitioned by date shows its partitions flattened, and the folders there that are one thing, their names alike
        but for their dates, as one folder grouping them; any other folder shows what it holds. Where entries from partitions
        share a name, each is led by the partition it is in, as the Lake's layout leads a name with its date."""
        if isinstance(real, list):
            entries = [([(row, place, partition)], partition)
                       for folder, partition in real for row, place in self._held(fs, folder)]
        else:
            self._discover(fs, real, ' › '.join(here.parts[1:]))
            groups = defaultdict(list)
            for row, place, partition in self._flattened(fs, self._held(fs, real)):
                alike = partition and row['gppu']['type'] == 'folder'   # only folders that came from a partition are grouped
                groups[('', self._key(self._shown(row)).casefold()) if alike else (place.casefold(), '')].append((row, place, partition))
            entries = [(members, members[0][2] if len(members) == 1 else '') for members in groups.values()]
        names = [self._shown(members[0][0]) if len(members) == 1 else self._key(self._shown(members[0][0])) for members, _ in entries]
        counts = Counter(name.casefold() for name in names)
        shown_as, rows = {}, []
        for (members, partition), name in zip(entries, names):
            name = f'{partition} {name}' if counts[name.casefold()] > 1 and partition else name
            if len(members) == 1:
                row, place, _ = members[0]
                shown_as[name.casefold()] = place
                rows.append(self._row(row, str(here / name)))
            else:
                shown_as[name.casefold()] = [(place, partition) for _, place, partition in members]
                self._groups[str(here / name).casefold()] = self._group(members, str(here / name))
                rows.append(self._groups[str(here / name).casefold()])
        return rows, shown_as

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
        fs, real = self._real(path)
        if not isinstance(fs, GppuFileSystem):
            return fs.info(real) | {'name': '/' + '/'.join(parts)}
        if isinstance(real, list):
            return self._groups[('/' + '/'.join(parts)).casefold()] | {'name': '/' + '/'.join(parts)}
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
        if isinstance(real, list):
            raise IsADirectoryError(path)
        return fs.open(real, mode=mode, **kwargs)


def mount(sources: dict[str, AbstractFileSystem], mount_point: str) -> None:
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
