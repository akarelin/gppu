r"""gppufs: GppuFileSystem, the fsspec file system of a location with a SQLite index beside each folder it lists, and the
filesystems it indexes besides files: Postgres and SharePoint. It needs no database."""
import io
import json
import os
import posixpath
import re
import ctypes
import shutil
import socket
import sqlite3
import time
import tempfile
from collections.abc import Callable, Mapping
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, Protocol, runtime_checkable
from urllib.parse import quote
from threading import RLock
from fsspec import register_implementation
from fsspec.archive import AbstractArchiveFileSystem
from fsspec.core import url_to_fs
from fsspec.implementations.local import LocalFileSystem
from fsspec.spec import AbstractFileSystem
from fsspec.utils import stringify_path
from ..gppu import TimeSpan, full_path, sync, Warn
from . import handlers, UNSAFE, _address, _below, _display_order, _metadata_text, _modified, _probe_name, _scratch


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


# The most an index holds before the folder below it holding the most of it gets an index of its own (Alex's proposal of
# 2026-10-21, D:\Work\10\21\gppufs-index-size): about 28,000 entries at the 2.3 KB each D:'s index measured (419,042 entries
# in 958 MB), well above every other index on alex-pc, the largest of which held 27 MB.
INDEX_LIMIT = 64 * 2**20

# The filesystems a Linux host mounts another host's folders with: such a folder is not this host's to write an index in.
NETWORK_FILESYSTEMS = ('cifs', 'smb3', 'smbfs', 'nfs', 'nfs4', 'afpfs', 'fuse.sshfs')


# A folder's address -> the index it holds, asked of its store once in this process: every gppufs here reads it, and
# records the index it makes, moves or removes.
_INDEXES: dict[str, str | None] = {}

# What git leaves out of a repository an index is written in: gppufs's index files and SQLite's companions to them.
GIT_EXCLUDE = '*.gppufs.sqlite*'
_EXCLUDED: set[str] = set()   # the folders whose indexes this process has seen to, in a repository or in none


def _excluded_from_git(folder: str) -> None:
  """An index written inside a git work tree is left out of that repository: `GIT_EXCLUDE` in the repository's own
  info/exclude, which is the clone's and never committed, so the index stays beside its location and no .gitignore
  changes. A worktree's or a submodule's .git is a file naming its git folder, whose commondir names the shared one."""
  if folder in _EXCLUDED:
    return
  _EXCLUDED.add(folder)
  top = next((p for p in (Path(folder), *Path(folder).parents) if (p / '.git').exists()), None)
  if top is None:
    return
  git = top / '.git'
  if git.is_file():
    git = (top / git.read_text(encoding='utf-8').split(':', 1)[1].strip()).resolve()
  if (common := git / 'commondir').is_file():
    git = (git / common.read_text(encoding='utf-8').strip()).resolve()
  exclude = git / 'info' / 'exclude'
  if not exclude.is_file() or GIT_EXCLUDE not in exclude.read_text(encoding='utf-8').splitlines():
    exclude.parent.mkdir(exist_ok=True)
    with exclude.open('a', encoding='utf-8') as f:
      f.write(f'\n{GIT_EXCLUDE}\n')


def _remote(root: str) -> bool:
  """Whether a local path is on another host: a UNC share, a Windows drive letter mapped to one, or a folder a Linux host
  mounts over the network, such as trix's /mnt/S1/Lake. A host without /proc, macOS, has its mounts taken as its own."""
  if root.startswith('//'):
    return True
  if os.name == 'nt':
    drive = PureWindowsPath(root).drive
    return bool(drive) and ctypes.windll.kernel32.GetDriveTypeW(drive + '\\') == 4   # DRIVE_REMOTE
  mounts = Path('/proc/self/mounts')
  if not mounts.exists():
    return False
  here = os.path.realpath(root)
  points = [line.split()[1:3] for line in mounts.read_text(encoding='utf-8').splitlines()]
  kind = max(((point.replace('\\040', ' '), kind) for point, kind in points
              if here == point or here.startswith(point.rstrip('/') + '/')), key=lambda found: len(found[0]), default=('', ''))[1]
  return kind in NETWORK_FILESYSTEMS


def _signature(path: str | None) -> tuple[int, int] | None:
  """Which version of a file is there, by its modified time and size; None when there is none."""
  if path is None or not os.path.isfile(path):
    return None
  status = os.stat(path)
  return status.st_mtime_ns, status.st_size


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
  # The folders directly below an index's own, the one holding the most of it first: what a split moves (`_bound`).
  _largest = '''SELECT top FROM (SELECT substr(path, 1, instr(path, '/') - 1) AS top,
        sum(length(metadata) + coalesce(length(children), 0)) AS held FROM gppufs_entries WHERE instr(path, '/') > 0 GROUP BY top)
    WHERE top NOT IN (SELECT path FROM gppufs_entries WHERE metadata->>'$.type' <> 'directory') ORDER BY held DESC LIMIT 1'''
  # A folder's rows moved from the owner's index into the folder's own, their paths and the paths in their listings made
  # relative to the folder (`_split`).
  _moved = '''INSERT INTO gppufs_entries SELECT at, json_set(metadata, '$.name', at, '$.gppu.path', at),
      CASE WHEN children IS NULL THEN NULL ELSE (SELECT json_group_array(json(json_set(value, '$.path',
        CASE WHEN value->>'$.path' = :here THEN '.' ELSE substr(value->>'$.path', :cut) END)))
        FROM (SELECT value FROM json_each(children) ORDER BY key)) END
    FROM (SELECT CASE WHEN path = :here THEN '.' ELSE substr(path, :cut) END AS at, metadata, children
      FROM owner.gppufs_entries WHERE path = :here OR substr(path, 1, :cut - 1) = :prefix) WHERE true
    ON CONFLICT(path) DO UPDATE SET metadata=excluded.metadata, children=excluded.children'''
  # The folders below that hold an index of their own: a listing here names them, and their rows are in their own index.
  _nested = '''SELECT DISTINCT child.value->>'$.path' FROM gppufs_entries, json_each(gppufs_entries.children) AS child
    WHERE child.value->>'$.type' = 'directory' AND child.value->>'$.path' NOT IN (SELECT path FROM gppufs_entries)'''
  _aggregate = f'''SELECT count(*) FILTER (WHERE kind='folder'), count(*) FILTER (WHERE kind='file'),
      coalesce(sum(size) FILTER (WHERE kind='file'), 0), min(mtime) FILTER (WHERE kind='file'), max(mtime) FILTER (WHERE kind='file'),
      max(probed), count(*) FILTER (WHERE kind='file' AND path LIKE '%.md'), count(*) FILTER (WHERE session)
    FROM (SELECT path, metadata->>'$.gppu.type' AS kind, metadata->>'$.gppu.size' AS size,
        unixepoch(metadata->>'$.gppu.modified_at', 'subsec') AS mtime,
        metadata->>'$.gppu.probed_at' AS probed,
        EXISTS (SELECT 1 FROM json_each(metadata, '$.gppu.handlers') WHERE value='session') AS session
      FROM gppufs_entries WHERE path<>'.'
        AND coalesce(metadata->>'$.gppu.record.type', '') NOT IN ({", ".join(f"'{s}'" for s in handlers.IGNORED)}))'''

  def __init__(self, location: str | Path, locations: Mapping[str, Mapping[str, str]] | None = None,
               index: GppuIndex | None = None, cache: bool = True, **storage_options: Any) -> None:
    """`cache=False` writes no index file into the location: a folder another program watches, such as a harness's
    sessions, holds its index in memory for this instance, as another host's share does."""
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
    # Only the host a location belongs to writes its indexes: an index file is written only on this host's own disk. Another
    # host's share and every other store hold theirs in memory for this instance, read from the store and never written back.
    self._cacheless = not cache or not isinstance(self.fs, LocalFileSystem) or _remote(self.root)
    self._memory: dict[str, sqlite3.Connection] = {}   # a remote store's index, held for this instance
    self._working: dict[str, list] = {}   # an index's path -> [its copy in the cache, the file it was copied from, changed]
    self._scratch: tempfile.TemporaryDirectory | None = None   # where the copies are, made at the first write
    self._copies = 0                 # how many copies were made there
    self._running = 0                # how many runs are open: their writes reach the folders when the last one ends
    self._locations = dict(locations) if locations else {}   # folder -> the location that is there
    self._here: str | None = None   # the root as the location map names folders, resolved once
    self._database_path(self.root)  # Validate the required location name.

  def _on_host(self, key: str) -> str:
    """Where an entry is on this host, as the location map names folders: the root, resolved once, and the key below
    it. Nothing below the root is followed as a link, and on a share each resolve is a round trip."""
    if self._here is None:
      self._here = full_path(self.root).as_posix()
    return self._here if key == '.' else f"{self._here.rstrip('/')}/{key}"

  def _location_of(self, key: str) -> dict[str, str] | None:
    """Which configured location an entry on this host is, or is inside: its location, canonical address, the entry's
    address and its folder in it, the deepest location containing it winning; None when none does."""
    here = self._on_host(key)
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
    """Whether a folder holds an index of its own, asked of the store once per folder in this process.

    ``_owner`` asks this of every ancestor of every entry, and each ask is a round trip on a store that
    is not this host's and on a share this host mounts, where a folder without an index is also listed
    for one renamed with it: a listing of a share's folder would otherwise ask every folder above it
    again for each of its entries. gppufs is what makes, moves and removes that file, and records it in
    ``_INDEXES`` when it does, so the answer holds for every gppufs in this process.
    """
    address = self.fs.unstrip_protocol(folder)
    if address not in _INDEXES:
      _INDEXES[address] = self._index_at(folder)
    return _INDEXES[address]

  def _forget_indexes(self, folder: str) -> None:
    """What this process knows of the indexes in a folder and below it, dropped: the folder moved, or its index did."""
    address = self.fs.unstrip_protocol(folder).rstrip('/')
    for known in [known for known in _INDEXES if known == address or known.startswith(address + '/')]:
      del _INDEXES[known]

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
    """The location's index: the file in its folder, read in place, until this instance writes it; from then on a copy in
    the cache, put into the folder whole (`_put`). In memory when the store is not this host's own disk, or the folder is
    one this account cannot write.

    Alex, 2026-09-17 03:49: "local databases are caches for runtime and original indexes (often only
    copy because original is a rar file now). / Local dbs are not synced in many cases. Don't count on
    these being present". So this is a cache and never the answer: the index a lookup asks is the one
    in Postgres. Alex's proposal of 2026-10-21 (D:\\Work\\10\\21\\gppufs-index-size): an index is replaced
    whole, never written in place, so a sync client, a share or another desktop only ever sees a complete
    file; and only the host a location belongs to writes its indexes, so a share, another host's or the
    Lake, is read and never written.
    """
    path = self._database_path(self._path(owner))
    if not self._cacheless and os.path.isdir(self._path(owner)) and os.access(self._path(owner), os.W_OK):
      working = self._working_copy(owner, path, write)
      if working is None:
        yield None
        return
      opened = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True) if working == path else sqlite3.connect(working)
      with closing(opened) as database:
        with database:
          if write:
            self._prepare(database, owner, self._columns_of(database))
          yield database
      if write:
        self._working[path][2] = True
        if not self._running:
          self._put(path)
      return
    database = self._held(owner)
    with database:
      if write:
        self._prepare(database, owner, self._columns_of(database))
      elif not self._columns_of(database):
        yield None
        return
      yield database

  def _working_copy(self, owner: str, path: str, write: bool) -> str | None:
    """The file owner's index is read in: its copy in the cache once this instance writes it, taken from the file in the
    folder at the first write; that file itself until then; None when there is neither and nothing is written. A copy whose
    file changed in the folder since it was taken, by another writer, is taken again, and refused if it holds writes this
    instance has not put yet."""
    held = self._existing_index(self._path(owner))
    seen = _signature(held)
    if path in self._working:
      copy, taken, changed, _ = self._working[path]
      if taken == seen:
        return copy
      if changed:
        raise RuntimeError(f'{path}: changed in its folder while this instance held writes to put into it')
      del self._working[path]
    if not write:
      return held if seen is not None else None
    copy = self._fresh()
    if seen is not None:
      shutil.copyfile(held, copy)
    self._working[path] = [copy, seen, False, owner]
    _INDEXES[self.fs.unstrip_protocol(self._path(owner))] = path   # gppufs holds it: known without asking the store
    return copy

  def _fresh(self) -> str:
    """A name in the cache no copy has had."""
    if self._scratch is None:
      self._scratch = _scratch('gppufs-')
    self._copies += 1
    return os.path.join(self._scratch.name, f'{self._copies}.sqlite')

  def _put(self, path: str) -> None:
    """An index this instance wrote, put into its folder whole: staged beside it and moved into place, as FileSystem.write
    puts a file, so the folder never holds part of one."""
    copy, taken, changed, owner = self._working[path]
    if not changed:
      return
    if os.path.lexists(path) and not os.path.isfile(path):
      return self._hold(path)   # something else is where the index would go
    if _signature(path) != taken:
      raise RuntimeError(f'{path}: changed in its folder while this instance held writes to put into it')
    folder = os.path.dirname(path)
    try:
      staged = tempfile.NamedTemporaryFile(dir=folder, prefix='.', suffix='.pending', delete=False)
    except PermissionError:
      return self._hold(path)   # a folder this account cannot write
    _excluded_from_git(folder)
    with staged:
      pending = Path(staged.name)
      try:
        with open(copy, 'rb') as source:
          shutil.copyfileobj(source, staged)
        staged.flush()
        os.fsync(staged.fileno())
      except BaseException:
        staged.close()
        pending.unlink()
        raise
    try:
      os.replace(pending, path)
    except PermissionError as error:
      raise PermissionError(f'{path}: not replaced; on Windows a process holding it open refuses it') from error
    finally:
      pending.unlink(missing_ok=True)
    self._working[path] = [copy, _signature(path), False, owner]

  def _hold(self, path: str) -> None:
    """A folder that will not take its index: what this instance wrote is held in memory, as a store that is not this
    host's disk holds it, and this instance writes no index file again. Alex, 2026-09-17: "Don't count on these being
    present"; only the cache is lost."""
    copy, _, _, owner = self._working.pop(path)
    database = sqlite3.connect(':memory:', check_same_thread=False)
    with closing(sqlite3.connect(copy)) as written:
      written.backup(database)
    self._memory[owner] = database
    self._cacheless = True

  def _put_all(self, key: str = '.') -> None:
    """Every index this instance wrote at and below key, put into its folder, the deepest first: an index is in place
    before the listing above it that leads to it."""
    folder = self._path(key).rstrip('/')
    below = [path for path in self._working if key == '.' or os.path.dirname(path) == folder
             or os.path.dirname(path).startswith(folder + '/')]
    for path in sorted(below, key=lambda item: len(PurePosixPath(item).parts), reverse=True):
      self._put(path)

  def _let_go(self, key: str) -> None:
    """The indexes at and below key put into their folders and their copies dropped: the folder is about to move."""
    self._put_all(key)
    folder = self._path(key).rstrip('/')
    for path in [path for path in self._working if key == '.' or os.path.dirname(path) == folder
                 or os.path.dirname(path).startswith(folder + '/')]:
      del self._working[path]

  @contextmanager
  def run(self):
    """Writes that reach their folders together: every index a run writes is built in the cache and put into its folder
    whole when the run ends, however it ends, the deepest first. A share, a sync client or another desktop sees only
    complete files, and a run that stops keeps what it wrote. FileIndexer's index of a selection is one run; a write
    outside a run is put as soon as it is made."""
    with self._lock:
      self._running += 1
    try:
      yield self
    finally:
      with self._lock:
        self._running -= 1
        if not self._running:
          self._put_all()

  def _bound(self, owner: str) -> None:
    """No index past INDEX_LIMIT: while owner's holds more, the folder directly below it holding the most of it gets an
    index of its own (`_split`), and the same holds again in that one, so however large a folder, an index is larger
    than the limit only by one folder's own entries. Only an index this host writes is bounded."""
    if self._database_path(self._path(owner)) not in self._working:
      return   # an index this instance holds in memory, or has not written
    while True:
      with self._database(owner) as database:
        if database is None:
          return
        pages, free, size = (database.execute(f'PRAGMA {name}').fetchone()[0]
                             for name in ('page_count', 'freelist_count', 'page_size'))
        if (pages - free) * size <= INDEX_LIMIT or not (top := database.execute(self._largest).fetchone()):
          return
      folder = self._absolute(top[0], owner)
      self._split(owner, folder)
      self._bound(folder)

  def _split(self, owner: str, folder: str) -> None:
    """folder, below owner, given an index of its own: its row and the rows below it move into the new index, their paths
    made its. The listing above it still names it, which is how `stats` finds the folders below that hold their own index.
    The new index is recorded in `_INDEXES` as gppufs makes it. A folder that holds an index already owns its rows there,
    so owner's copies of them, which nothing reads, are dropped and not moved again."""
    here = self._relative(folder, owner)
    with self._database(owner, write=True):
      pass   # owner's copy in the cache, which the rows move from inside SQLite, none of them read into memory
    if self._existing_index(self._path(folder)) is None:
      with self._database(folder, write=True) as database:
        database.commit()
        database.execute('ATTACH DATABASE ? AS owner', (self._working[self._database_path(self._path(owner))][0],))
        database.execute(self._moved, dict(here=here, cut=len(here) + 2, prefix=here + '/'))
        database.commit()
        database.execute('DETACH DATABASE owner')
    index = self._database_path(self._path(owner))
    compact = self._fresh()
    with self._database(owner, write=True) as database:
      database.execute('DELETE FROM gppufs_entries WHERE path=? OR substr(path,1,?)=?', (here, len(here) + 1, here + '/'))
      database.commit()
      database.execute('VACUUM INTO ?', (compact,))   # the file is then the size of what it holds, not of what it held
    os.remove(self._working[index][0])
    self._working[index][0] = compact

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
      located = self._location_of(key)
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
    # Archive members do not change their physical archive's byte count, and an ignored file parses to nothing.
    if not in_archive and scope in rows:
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
    with self.run():
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
      for owner in grouped:
        self._bound(owner)

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
      self._forget_indexes(self._path(old))
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

  def _inventory(self, fs: AbstractFileSystem, root: str) -> dict[str, dict]:
    # fsspec's archive info omits an empty archive root; it is still listable.
    native = {root: {'name': root, 'type': 'directory', 'size': 0}
      if isinstance(fs, AbstractArchiveFileSystem) and root in ('', '/') else fs.info(root)}
    if native[root]['type'] != 'directory' or native[root].get('islink'):
      return native
    if _probe_name(PurePosixPath(root).name, True).type == 'ignored':
      return native
    for _, directories, files in fs.walk(root, detail=True, on_error='raise'):
      for item in (*directories.values(), *files.values()):
        if not self._index_name.fullmatch(PurePosixPath(item['name']).name):
          native[item['name'].rstrip('/')] = fs.info(item['name'])
      for name in tuple(directories):
        if _probe_name(PurePosixPath(name).name, True).type == 'ignored' or directories[name].get('islink'):
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

    def read(name: str) -> tuple[str, dict] | None:
      item = native[name]
      relative = '.' if name == source else PurePosixPath(name).relative_to(base).as_posix()
      address = self._member_address(key, relative)
      directory = item['type'] == 'directory'
      record = _probe_name(PurePosixPath(name).name or 'location', directory, item.get('size'))
      if self._unindexed(record, directory):
        return None
      handler, unread = handlers.HANDLERS.get(record.type), None
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
      children = [found for child in sorted(below.get(name, ()), key=lambda child: (
        native[child]['type'] != 'directory', child.casefold())) if (found := read(child)) is not None] if directory else []
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
      if self._unindexed(record, item['type'] == 'directory'):
        continue
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
      if self._unindexed(record, item['type'] == 'directory'):
        return None
      handler = handlers.HANDLERS.get(record.type)
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
    return record.type in handlers.FOLDERS

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
    if gppu['record']['type'] in handlers.IGNORED:
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
    names = [record.type]
    if path.name.casefold().endswith(handlers.ARCHIVES):
      names.append('archive')
    located = self._location_of(key) if isinstance(self.fs, LocalFileSystem) else None
    if located is not None:
      names.append('location')
    gppu = {'path': str(path), 'type': 'folder' if folder else 'file',
            'size': 0 if folder else int(record.meta.get('size', 0)), 'modified_at': _modified(item),
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
    with self.run():
      for owner, values in grouped.items():
        with self._database(owner, write=True) as database:
          database.executemany('INSERT INTO gppufs_entries VALUES (?, ?, ?) ON CONFLICT(path) DO NOTHING', values)
      if listing is not None:
        owner = self._owner(key)
        with self._database(owner, write=True) as database:
          database.execute('UPDATE gppufs_entries SET children=? WHERE path=?', (json.dumps([
            {**entry, 'path': self._relative(entry['path'], owner)} for entry in listing]), self._relative(key, owner)))
        grouped.setdefault(owner, [])
      for owner in grouped:
        self._bound(owner)

  @staticmethod
  def _unindexed(record: handlers.Record, directory: bool) -> bool:
    """Whether an entry is left out of the index and of listings: an ignored file. An ignored folder is listed, and a
    recursion does not enter it, as FileIndexer's walk does."""
    return record.type == 'ignored' and not directory

  def _identify_entry(self, key: str) -> tuple[dict, None] | None:
    """Index one entry from its native attributes and matching handlers, without probing, and give what the index holds
    of it; an ignored file is identified and not indexed."""
    path = self._path(key)
    item = self.fs.info(path)
    record = handlers.probe(Path(path)) if isinstance(self.fs, LocalFileSystem) else self._listed(key, item)
    row = self._row(key, item, record, Path(path))
    if self._unindexed(record, item['type'] == 'directory'):
      return self._for_index(key, row), None
    self._store(key, {key: (row, None)}, None)
    return self._stored(key)

  def _unlocated(self, key: str) -> bool:
    """Whether the index holds this entry from before a configured location covered it.

    The location map is the caller's, not the folder's, so a row identified without it is
    out of date the moment the configuration names the place. Such a row is identified
    again; every other stored row is kept.
    """
    if not self._locations or not self._location_of(key):
      return False
    stored = self._stored(key)
    return stored is not None and 'location' not in stored[0]['gppu']

  def _misread(self, key: str, entry: dict) -> bool:
    """Whether the index holds a folder on this host as read by another handler than the one probe gives it now, as a
    folder stored before its handler was added is: probe tells a folder's handler by its path, nothing read."""
    if entry['type'] != 'directory' or not isinstance(self.fs, LocalFileSystem):
      return False
    stored = self._stored(key)
    return stored is not None and (stored[0]['gppu'].get('record') or {}).get('type') != handlers.probe(Path(self._path(key))).type

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
      stored = self._stored(child_key) if child_key in known else None
      if stored is not None and stored[0]['type'] != 'directory' and 'ignored' in stored[0]['gppu']['handlers']:
        self._forget(child_key)   # an ignored file an earlier listing indexed
        continue
      if self._unlocated(child_key) or (child_key in known and self._misread(child_key, entry)):
        self._forget(child_key)   # the stored row predates the location or the folder's handler; an insert alone would keep it
      elif child_key in known:
        listing.append(known[child_key])
        continue
      if local:
        item = self.fs.info(name)  # A directory scan reports no inode on Windows; rename recovery needs it.
        record = handlers.probe(Path(self._path(child_key)))
      else:
        item = entry            # a store that lists enough said it all once; asking again is a call per entry
        record = self._listed(child_key, item)
      if self._unindexed(record, item['type'] == 'directory'):
        continue
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

  def stats(self) -> dict[str, Any]:
    """What this location's own index holds, aggregated in the index and touching no filesystem: its folders and files, the
    files' bytes, the first and the last modified time among them, when the latest entry was probed, its notes (.md) and its
    sessions (what the session handler read). An ignored entry is not counted, as a row's totals do not count it. The
    indexes gppufs split off below it count with it (`_split`); a location below it, holding its own, does not."""
    with self._lock:
      folders, files, size, first, last, seen, notes, sessions = self._aggregated('.')
    return dict(folders=folders, files=files, bytes=size, notes=notes, sessions=sessions,
                first=None if first is None else datetime.fromtimestamp(first, timezone.utc).astimezone(),
                last=None if last is None else datetime.fromtimestamp(last, timezone.utc).astimezone(),
                seen=None if seen is None else datetime.fromisoformat(seen))

  def spans(self, path: str | Path | None, depth: int) -> dict[str, TimeSpan]:
    """The span of the files below a folder, from the first to the last modified time, for each path below it that its first
    depth names give: aggregated in the folder's index, touching no filesystem, what the things of a partitioned folder span
    when depth is where its things are. The indexes split off below the folder are not asked."""
    with self._lock:
      key = self._key(path)
      owner = self._owner(key)
      here = self._relative(key, owner)
      with self._database(owner) as database:
        if database is None:
          return {}
        rows = database.execute(self._spanned(here, depth), {'low': f'{here}/', 'high': f'{here}0'}).fetchall()
    return {prefix: TimeSpan(datetime.fromtimestamp(first).astimezone(), datetime.fromtimestamp(last).astimezone())
            for prefix, first, last in rows}

  @staticmethod
  def _spanned(here: str, depth: int) -> str:
    """The aggregate spans() asks: each file's path below here cut after its depth-th name, and the first and the last
    modified time of the files under each cut; a path range below here, so the index's key is used."""
    below = 'path' if here == '.' else f'substr(path, {len(here) + 2})'
    end = '0'
    for _ in range(depth):
      end = f"({end} + instr(substr({below} || '/', {end} + 1), '/'))"
    return f'''SELECT prefix, min(mtime), max(mtime) FROM (SELECT substr({below}, 1, {end} - 1) AS prefix,
        unixepoch(metadata->>'$.gppu.modified_at', 'subsec') AS mtime FROM gppufs_entries
        WHERE {'' if here == '.' else 'path > :low AND path < :high AND '}metadata->>'$.gppu.type' = 'file'
          AND coalesce(metadata->>'$.gppu.record.type', '') NOT IN ({", ".join(f"'{s}'" for s in handlers.IGNORED)}))
      WHERE mtime IS NOT NULL GROUP BY prefix'''

  def _aggregated(self, owner: str) -> list:
    """owner's index aggregated in it, with what the indexes of the folders below it hold, but for a configured location's,
    which is its own."""
    with self._database(owner) as database:
      if database is None:
        return [0, 0, 0, None, None, None, 0, 0]
      held = list(database.execute(self._aggregate).fetchone())
      nested = [self._absolute(path, owner) for (path,) in database.execute(self._nested).fetchall()]
    for key in nested:
      if self._on_host(key) in self._locations:
        continue
      below = self._aggregated(key)
      below[0] += 1   # the folder itself, whose row is its own index's root
      for i, combined in ((0, sum), (1, sum), (2, sum), (3, min), (4, max), (5, max), (6, sum), (7, sum)):
        held[i] = combined(value for value in (held[i], below[i]) if value is not None) if any(
          value is not None for value in (held[i], below[i])) else None
    return held

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
        cached = self._identify_entry(key)
      elif cached is None and not refresh:
        self._identify_inside(key)   # a member is known from its archives' listings
        cached = self._stored(key)
      if cached is None and refresh:
        self._live(key)
        cached = self._stored(key)
        if cached is None and self._identifiable(key):
          cached = self._identify_entry(key)   # an ignored file: nothing is parsed or indexed of it, it is what probe says
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
          below = self.ls_sync(row['name'], recurse=True, refresh=refresh, live=live)
          result.append(self._stored(child['path'])[0])   # the folder as reading it left it
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
      self._let_go(source)
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
    with self._lock:
      self._let_go(source)
    other.fs.mkdirs(other._path(other._parent_key(arriving) or '.'), exist_ok=True)
    if type(self.fs) is type(other.fs) and isinstance(self.fs, LocalFileSystem):
      self.fs.mv(here, there, recursive=True)
    else:
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
    with self._lock:
      self._let_go('.')
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
      self._forget_indexes(self.root)
    return kept

  def _address_of(self, key: str) -> str:
    """The address an entry had, worked out from the location map rather than from the vanished path."""
    if self._locations:
      here = self._on_host(key)
      for folder in sorted(self._locations, key=lambda item: len(item), reverse=True):
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


