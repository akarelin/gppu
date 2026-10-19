r"""gppufs on Linked Data: gppu.fs as it is, its configuration and its index kept by Linked Data's files API (gppu.ld.files) and
reached through it only, at the address the caller gives connect(). The app using it loads its own configuration into gppu's Env:
`drives`, where a Windows host's WSL mounts its drives, is read from it (Drives).

  catalog()     gppu.fs.GppuCatalog made from GET /files/locations: every location with a uid and a canonical uri, each reached
                over its own data.handler, its connection. Its Providers are gppufs's own, FileSystem for file://, and those a
                caller gives, as GppuCatalog takes them: the Locations and Containers FileIndexer and every gppufs user reach
                files through
  collection()  gppu.fs.Collection, the Lake, over the catalog, a Location's configuration written back by store()
  Index         gppu.fs.GppuIndex over /files: what a GppuFileSystem's handlers read, kept by address, so a GppuFileSystem
                given it asks Linked Data first and runs a handler only for what it does not hold (filesystem())
  contents()    a folder's contents compared with what is stored under it, written in one call (PUT /files): FileIndexer's
                and the Index's write
  record()      a walk's row (gppu.fs.walk_files, Container.walk) as the file record it is, not yet written

A record's data is what gppufs's handlers read: the handlers that matched, the stats, each handler's reading under its name. Its
meta is what the file system says of it, its size and time, a boundary or an ignore rule, what could not be read, and how the
record came to be (Linked Data.md: "`meta` how the record came to be: who made it, from what, when it was seen"). A location's
and a container's data is configuration, so what gppufs reads of them goes to their meta only."""
import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

from ..fs import Collection, FileSystem, GppuCatalog, GppuFileSystem, Location, _address
from ..gppu import TimeSpan, full_path, glob

client: httpx.Client   # the API, opened by connect()
DELETED = 'deleted'   # the status of a file its folder no longer holds (Linked Data.md, # API ## Types: FileIndexer sets it); the store keeps the record
CONFIGURED = ('location', 'container')   # under a location, configuration beside what a walk finds: never one of a folder's entries, its data never a reading
FOLDERS = ('folder', 'git', 'ignored', 'system')   # what a refresh lists, so the only entries a refresh says are gone
META = ('size', 'modified_at', 'unread', 'errors', 'boundary', 'target', 'ignored_reason')   # what a walk's row says of the file system's object: its meta
CALCULATED = ('path', 'name', 'parent')   # what gppufs calculates of an entry from where it is, so the record does not keep (Files.md, # Calculated)
ARCHIVES = {'.zip': 'ZIP', '.rar': 'RAR', '.tar.gz': 'tar.gz'}   # an archive's format, by gppu.fs.ArchiveHandler's extensions
SYSTEM = 'folder:FILE_ATTRIBUTE_SYSTEM'   # the ignore rule of a folder with the system attribute (gppu.fs.IgnoredHandler.reason)
GIT = '.git'   # a folder holding it is a git repository, as its listing says: the walk has no git handler, and gppufs's matches every path a repository tracks


def connect(url: str) -> None:
    """Open Linked Data's API at url. One connection serves every call: a connection a call left 11,811 sockets waiting after one walk
    and ran this host out of ports (WinError 10048)."""
    global client
    if not url:
        raise ValueError("Linked Data's API address is required")
    client = httpx.Client(base_url=url, timeout=300)


def api(method: str, path: str, body: Any = None, **params: Any) -> Any:
    """One call to the API, its answer as JSON; a refusal raises with what the API said (a 422 carries Postgres' reason), a 404 as LookupError."""
    r = client.request(method, path, json=body, params=params)
    if r.is_error:
        raise (LookupError if r.status_code == 404 else ValueError)(f'{method} {path}: {r.status_code} {r.text}')
    return r.json()


def files(**columns: Any) -> list[dict]:
    """Every file whose columns equal these: GET /files by filters, every match, since no limit is given. It is search, not list: a
    folder is compared with all it holds however many, and a list (GET /files/{id}/files) is refused past its safe limit."""
    return api('GET', '/files', filters=json.dumps({k: {'$eq': str(v)} for k, v in columns.items()}))['items']


def verified(r: dict) -> bool:
    return bool(r['meta'].get('verified'))


def jsonable(v: Any) -> Any:
    """A value gppufs read, as jsonb takes it; a time in local time, as Alex reads them."""
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if isinstance(v, TimeSpan):
        return {'start': jsonable(v.start), 'end': jsonable(v.end)}
    if isinstance(v, datetime) and v.tzinfo:
        return v.astimezone().isoformat()
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)


def local(uri: str) -> Path | None:
    """The path on this host a file uri names (gppu.fs.FileSystem.local); none when it names another host or is not a file uri."""
    try:
        return FileSystem().local(uri)
    except ValueError:
        return None


class Drives(FileSystem):
    """gppufs's FileSystem in a Windows host's WSL: a file uri naming a drive, file://alex-pc/D:/Dev, is that drive as WSL mounts it,
    /mnt/d/Dev (`drives` in the app's configuration), so a location configured on the host is walked from its WSL as it is configured."""

    def local(self, uri: Any) -> Path:
        parsed = urlsplit(str(uri))
        path = unquote(parsed.path)
        if len(path) >= 3 and path[0] == '/' and path[2] == ':':
            if not (drives := glob('drives')):
                raise ValueError("`drives`, where WSL mounts this host's drives, is not in the app's configuration")
            uri = urlunsplit(parsed._replace(path=quote(f"{drives}/{path[1].casefold()}{path[3:]}")))
        return super().local(uri)


def catalog(**location_types: Any) -> GppuCatalog:
    """gppufs's catalog of Linked Data's locations: the rows of GET /files/locations, each over its own connection, its data.handler.
    location_types are the Providers a caller adds by scheme, as GppuCatalog takes them; gppufs's FileSystem reaches file://, and in a
    Windows host's WSL, Drives does."""
    rows = api('GET', '/files/locations')
    return GppuCatalog({'locations': rows, 'connections': {r['uid']: r['handler'] for r in rows if r['connection']}}, location_types=location_types)


def store(location: Location | None, who: str, fields: dict[str, Any]) -> None:
    """A Location's configuration written as who, as gppufs's Collection stores it: into the location's record, a new one when location
    is None. Its name is the record's, its tags meta.tags, its parent the location with that uid, the rest its data; meta.generated says
    who wrote it and when (Alex's provenance, generated: {by, at}). A null removes a field."""
    if not who:
        raise ValueError('configuration author is required')
    fields, record = dict(fields), {'subtype': 'location', 'meta': {'generated': {'by': who, 'at': datetime.now().astimezone().isoformat()}}}
    if 'name' in fields:
        record['name'] = fields.pop('name')
    if 'tags' in fields:
        record['meta']['tags'] = fields.pop('tags')
    if 'parent' in fields:
        parent = fields.pop('parent')
        record['parent_id'] = parent and next(r['id'] for r in api('GET', '/files/locations') if r['uid'] == parent)
    record['data'] = fields
    if location is None:
        api('POST', '/files', record)
    else:
        api('PUT', f"/files/{location.data['id']}", record)


def collection(**location_types: Any) -> Collection:
    """gppufs's Collection, the Lake, over Linked Data: its Locations read from it (catalog()) and their configuration written back
    into it (store()); gppu.fs.api serves it as /config and /lake."""
    return Collection(lambda: catalog(**location_types), store)


def reached(catalog: GppuCatalog) -> dict[str, dict[str, str]]:
    """The folders on this host the catalog's locations are, as GppuFileSystem's locations map takes them: what addresses its entries."""
    return {full_path(path).as_posix(): {'location': uid, 'canonical': row['canonical']}
            for uid, row in catalog.locations.items() if (path := local(row['canonical'])) and path.is_dir()}


def filesystem(catalog: GppuCatalog, uid: str) -> GppuFileSystem:
    """The GppuFileSystem of a location this host reaches, its index Linked Data: what its handlers read is kept at the location's
    addresses, so another host or checkout asks the same records."""
    folders = reached(catalog)
    return GppuFileSystem(str(local(catalog.locations[uid]['canonical'])), locations=folders, index=Index({f['canonical'] for f in folders.values()}))


def walked(row: dict) -> str:
    """The subtype of a walk's row: a link, and a folder the walk does not enter, ignored (system for the system attribute); a folder;
    the file the archive handler matched, an archive; any other file."""
    boundary = row.get('boundary')
    if boundary == 'link' or (row['type'] == 'directory' and boundary):
        return 'system' if row.get('ignored_reason') == SYSTEM else 'ignored'
    if row['type'] == 'directory':
        return 'folder'
    return 'archive' if 'archive' in row['handlers'] else 'file'


def record(row: dict) -> dict | None:
    """A walk's row as the file record it is, not yet written, named by the last name of its path: what the handlers read its data,
    what the file system says of it its meta. None for a child location's root, which is that location's own record: its parent's
    walk reports it and does not enter it."""
    if row.get('boundary') == 'Location':
        return None
    name = row['name'].rpartition('/')[2]
    r = {'name': name, 'subtype': walked(row), 'data': jsonable({k: v for k, v in row.items() if k not in META + ('name', 'type')}),
         'meta': jsonable({k: row[k] for k in META if k in row})}
    if r['subtype'] == 'archive':
        r['data']['format'] = next(f for ext, f in ARCHIVES.items() if name.casefold().endswith(ext))
    return r


def under(records: list[dict]) -> list[dict]:
    """Everything under the records neither deleted nor verified, and what is under that: what goes with a folder its parent no longer holds."""
    out = []
    for r in records:
        if r['subtype'] != 'file':
            for c in files(parent_id=r['id']):
                if c['status'] != DELETED and not verified(c):
                    out += [c, *under([c])]
    return out


def again(held: dict, new: dict) -> dict:
    """What is sent for a record found again: its new reading, a deleted one no longer deleted; a location's or a container's, only
    its meta."""
    if held['subtype'] in CONFIGURED:
        return {'meta': new['meta']}
    return new | ({'status': None} if held['status'] == DELETED else {})


def listed(held: dict, child: dict) -> dict:
    """A child its folder lists again: a git repository stays one, since only its own listing says whether it is."""
    return {k: v for k, v in child.items() if k != 'subtype'} if held['subtype'] == 'git' and child['subtype'] == 'folder' else child


def contents(folder: dict, own: dict | None, children: list[dict], holds: set[str] | None = None, level: str = 'files',
             extra: list[dict] = ()) -> tuple[dict[str, dict], int]:
    """A folder's contents compared with what is stored under it and written in one call (PUT /files), as FileIndexer compares a folder
    with what is stored (Linked Data.md, # API ## Types). What it holds is read first. A child found again by its name is sent with the
    id it is stored under and merged into it, a deleted one no longer deleted; the rest are created under it. When the caller read all
    the folder holds (holds: every name in it), what is stored under another name is set deleted with everything under it, never
    removed; a refresh lists only folders, so only folders go deleted then. A record someone verified (meta.verified) is left as it is,
    unsent (FileIndexer 0.1.3: "Verified records are preserved"), and a location or a container under the folder by an entry's name is
    that place's own record, configuration a walk never writes as an entry nor sets deleted (an insert there would be merged into it).
    The folder itself is sent with own, its own reading. Records the caller changes besides (extra) go in the same call. The store
    writes all of it or none. Returns the children's stored records by name, and how many records went deleted."""
    stored = {r['name']: r for r in files(parent_id=folder['id'])}
    held = {name: r for name, r in stored.items() if r['subtype'] not in CONFIGURED}
    gone = [] if holds is None else [h for name, h in held.items() if name not in holds and h['status'] != DELETED and not verified(h)
                                     and (level != 'refresh' or h['subtype'] in FOLDERS)]
    gone += under(gone)
    kept = {c['name']: stored[c['name']] for c in children if c['name'] in stored and (stored[c['name']]['subtype'] in CONFIGURED or verified(stored[c['name']]))}
    itself = [] if own is None or verified(folder) else [again(folder, own) | {'id': folder['id']}]
    entries = [again(h, listed(h, c)) | {'id': h['id']} if (h := held.get(c['name'])) else c | {'parent_id': folder['id']}
               for c in children if c['name'] not in kept]
    written = api('PUT', '/files', itself + entries + [{'id': g['id'], 'status': DELETED} for g in gone] + list(extra))
    return kept | {r['name']: r for r in written[len(itself):len(itself) + len(entries)]}, len(gone)


def bare(address: str) -> str:
    """An address without a trailing slash; a scheme's root keeps its '://' (as gppu.fs.GppuCatalog compares them)."""
    scheme, _, rest = address.partition('://')
    return f'{scheme}://{rest.rstrip("/")}'


def parent_of(address: str) -> str | None:
    """The address of what holds the entry at address: a scheme's root holds what is right after it; none above a scheme's root."""
    scheme, _, rest = bare(address).partition('://')
    if not rest:
        return None
    head, slash, _ = rest.rpartition('/')
    return f'{scheme}://{head}' if slash else f'{scheme}://'


def name_of(address: str) -> str:
    return bare(address).partition('://')[2].rpartition('/')[2]


class Index:
    """gppu.fs.GppuIndex kept by Linked Data: an entry, named by its address, is the file record there (GET /files/address). Its
    metadata is the entry exactly as gppufs keeps it, its fsspec listing and its gppu reading without what gppufs calculates of it
    from where it is, in meta.gppufs, since the store keeps a null as no key; the record's data and meta say what the handlers read
    and what the file system says of it as well, as FileIndexer writes them. Its
    listing is the records under it this index was given, once it was given one (meta.enumerated, as FileIndexer marks a folder it
    listed). A put writes each folder's entries through contents(), parents first, a folder given its listing compared with what is
    stored under it; a move is a new parent and name (Files.md: a move is a new parent_id), so what is held of the thing moves with it.
    roots are the canonical uris of the locations a GppuFileSystem reaches: an entry at one is that location's root, its record the
    location's own."""

    def __init__(self, roots: set[str]) -> None:
        self.roots = {bare(r) for r in roots}

    def entry(self, address: str) -> tuple[dict, list[dict] | None] | None:
        """One entry's metadata and its listing, or None when no record is there or this index was never given it."""
        try:
            r = api('GET', '/files/address', uri=address)
        except LookupError:
            return None
        if 'gppufs' not in r['meta']:
            return None
        listing = None
        if r['meta'].get('enumerated'):
            listing = sorted(({'path': at, 'type': c['meta']['gppufs']['type'], 'ino': c['meta']['gppufs'].get('ino')}
                              for c in files(parent_id=r['id']) if 'gppufs' in c['meta'] and c['status'] != DELETED
                              and (at := c['data']['canonical'] if c['subtype'] == 'location' else _address(address, c['name']))
                              and parent_of(at) == bare(address)),
                             key=lambda c: (c['type'] != 'directory', c['path'].casefold()))
        return r['meta']['gppufs'] | {'name': address}, listing

    def put(self, entries: Mapping[str, tuple[dict | None, list[dict] | None]]) -> None:
        """Keep what the handlers read, by address. A None stands for a part this call does not change. The first entry of each branch,
        and a location's root, is found at its address or created there with the folders down to it, and written with its own reading;
        then the entries in this call under each folder are written in one call, and a folder given its listing is compared with what is
        stored under it."""
        given = {bare(a): v for a, v in entries.items()}
        tops = {a for a in given if parent_of(a) not in given or a in self.roots}
        stored = {a: self.placed(a, given[a][0]) for a in tops}
        for a in sorted(given, key=lambda a: a.count('/')):
            metadata, listing = given[a]
            children = [reading(c, m) for c, (m, _) in given.items() if parent_of(c) == a and m is not None and c not in tops]
            own = reading(a, metadata) if a in tops and metadata is not None else None
            if own is None and not children and listing is None:
                continue
            folder = stored[a] if a in stored else self.placed(a, metadata)
            holds = None if listing is None else {name_of(c['path']) for c in listing}
            if holds is not None:   # its listing: what it holds, and so whether it is a git repository
                own = (own or {'meta': {}}) | {'meta': (own or {'meta': {}})['meta'] | {'enumerated': True}}
                if (own.get('subtype') or folder['subtype']) in ('folder', 'git'):
                    own['subtype'] = 'git' if GIT in holds else 'folder'
            written, _ = contents(folder, own, children, holds)
            stored |= {_address(a, name): r for name, r in written.items()}

    def moved(self, source: str, destination: str) -> None:
        """The entry at source, and everything under it, is at destination now: its record gets the parent and the name destination
        gives it. An entry this index never held has nothing to move."""
        try:
            r = api('GET', '/files/address', uri=source)
        except LookupError:
            return
        api('PUT', f"/files/{r['id']}", {'parent_id': self.placed(parent_of(destination), None)['id'], 'name': name_of(destination)})

    def placed(self, address: str, metadata: dict | None) -> dict:
        """The record at address, or one made there, a folder unless metadata says what it is, with the folders down to it."""
        try:
            return api('GET', '/files/address', uri=address)
        except LookupError:
            if (parent := parent_of(address)) is None:
                raise LookupError(f'no location holds {address}')
        return api('POST', '/files', {'name': name_of(address), 'parent_id': self.placed(parent, None)['id'],
                                      'subtype': 'folder' if metadata is None else entered(metadata)})


def entered(metadata: dict) -> str:
    """The subtype of an entry a GppuFileSystem keeps: what its handlers matched, a link ignored, else a folder or a file. The git
    handler matches every path a repository tracks, so a git repository is told by its listing (put)."""
    gppu, handlers = metadata['gppu'], metadata['gppu']['handlers']
    if 'ignored' in handlers or metadata.get('islink'):
        return 'system' if gppu.get('ignored', {}).get('reason') == SYSTEM else 'ignored'
    if gppu['type'] == 'folder':
        return 'folder'
    return 'archive' if 'archive' in handlers else 'file'


def reading(address: str, metadata: dict) -> dict:
    """An entry a GppuFileSystem keeps, as the record written for it, as a walk's row is (record()): what its handlers read its data,
    what the file system says of it its meta, and the entry itself in meta.gppufs."""
    gppu = {k: v for k, v in metadata['gppu'].items() if k not in CALCULATED}
    return {'name': name_of(address), 'subtype': entered(metadata), 'data': jsonable({k: v for k, v in gppu.items() if k not in META}),
            'meta': jsonable({k: gppu[k] for k in META if k in gppu}) | {'gppufs': jsonable({k: v for k, v in metadata.items() if k not in ('gppu', 'name')} | {'gppu': gppu})}}
