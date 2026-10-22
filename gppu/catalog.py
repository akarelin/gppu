"""gppu.catalog: the catalog's API, /lake/catalog, and the filesystem a desktop browses it with. Its methods are specific to working with
the catalog and browsing it as the desktop's use cases do (SPEC_desktop.md), not generic, and a folder of any size is sent a row
at a time: neither the API nor its client asks the database for more than a fetch.

The catalog is the Lake's index in Postgres, schema `lake`: each entry in a tree by its parent's uid inside the location it is in,
with what each source read of it, its instances. Its locations are Linked Data's: an fs_location record whose entries are in the
catalog carries the catalog's id for it, `meta.lake_id`. Everything is reached by id, a location by its Linked Data id and an entry
by its uid; a path is only resolved into one.

  Catalog(dsn)            the catalog in the database at dsn, its locations read from Linked Data through gppu.ld.gppufs
  api(catalog)            the catalog as a FastAPI app, which an APIApp serves at /lake/catalog among its apis()
  CatalogFileSystem(url)  the catalog through its API as an fsspec filesystem: Linked Data's locations as folders, in each what
                          the catalog holds there; read-only

An entry is described by its columns: its content type and what SharePoint's columns hold for it, a statement's period, a tax
form's year, as text a file manager shows in a column of its own."""
import json
import re
from collections import Counter
from datetime import date, datetime
from typing import Any, Iterator
from uuid import UUID

from fsspec import AbstractFileSystem

FETCH = 1000   # the rows a cursor fetches at a time: a row read is about 2 kB with SharePoint's columns, so a fetch is about 2 MB,
# and the largest folder, 56,297 entries, takes 57 fetches; a row sent is about 300 bytes, its columns given as text

# What a listing shows of each entry: its latest instance, as the source that read it last read it; an entry gone from it is not shown
ENTRIES = """SELECT e.uid AS id, e.kind, e.name, i.size, i.files, i.folders, i.changed_at AS modified,
                    i.metadata->'columns'->>'Created' AS created, i.metadata->>'content_type' AS content_type,
                    i.metadata->'columns' AS columns
             FROM lake.entity e
             CROSS JOIN LATERAL (SELECT * FROM lake.instance WHERE entity_uid = e.uid ORDER BY read_at DESC LIMIT 1) i
             WHERE {inside} AND i.gone_at IS NULL ORDER BY e.name"""
# The entry a path names below a location's root, walked down a name at a time by the catalog's own unique indexes
AT = """WITH RECURSIVE walk(uid, depth) AS (
            SELECT uid, 1 FROM lake.entity WHERE location_id = %(location)s AND parent_uid IS NULL AND name = (%(names)s::text[])[1]
            UNION ALL
            SELECT e.uid, walk.depth + 1 FROM walk JOIN lake.entity e ON e.parent_uid = walk.uid AND e.name = (%(names)s::text[])[walk.depth + 1])
        SELECT uid FROM walk WHERE depth = cardinality(%(names)s::text[])"""
# One entry with every instance of it, the latest first
ENTRY = """SELECT e.uid AS id, e.location_id, e.parent_uid AS parent, e.kind, e.name, e.extension, e.created_at,
                  coalesce(json_agg(to_jsonb(i) - 'entity_uid' ORDER BY i.read_at DESC) FILTER (WHERE i.entity_uid IS NOT NULL), '[]') AS instances
           FROM lake.entity e LEFT JOIN lake.instance i ON i.entity_uid = e.uid WHERE e.uid = %s GROUP BY e.uid"""
# Each column SharePoint gave items, by how many carry it, and how many items it gave columns for
COLUMNS = """SELECT k AS name, count(*) AS n FROM lake.instance i, jsonb_object_keys(i.metadata->'columns') k
             WHERE jsonb_typeof(i.metadata->'columns') = 'object' AND i.gone_at IS NULL GROUP BY k ORDER BY n DESC, k"""
ITEMS = "SELECT count(*) AS n FROM lake.instance WHERE jsonb_typeof(metadata->'columns') = 'object' AND gone_at IS NULL"
WHEN = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')   # how SharePoint gives a date or a time


def _json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f'{type(value).__name__} is not JSON')


def _text(value: Any) -> str:
    """A column's value as a file manager shows it: a date or a time as the local date it falls on, a whole number without
    decimals, a term by its label, a link by its description, a list joined."""
    if isinstance(value, dict):
        return str(value.get('Label') or value.get('Description') or '')
    if isinstance(value, list):
        return ', '.join(_text(item) for item in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str) and WHEN.fullmatch(value):
        return datetime.fromisoformat(value).astimezone().date().isoformat()
    return '' if value is None else str(value)


def label(name: str) -> str:
    """A column's internal name, as SharePoint gives it, in words: _StartDate is Start Date, TaxYear is Tax Year."""
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name.replace('_x0020_', ' ').strip('_')).replace('_', ' ')


def paths(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Linked Data's locations by path, as the desktop shows them: each by its name, and by its name and uid where locations beside
    it share the name, as Windows shows one folder per name."""
    found = {row['id']: row for row in rows}
    names = Counter((row['parent'], row['name'].casefold()) for row in found.values())

    def path(row: dict[str, Any]) -> str:
        name = row['name'] if names[row['parent'], row['name'].casefold()] == 1 else f"{row['name']} ({row['uid'] or row['id']})"
        return f"{path(found[row['parent']])}/{name}" if row['parent'] else name
    return {path(row): row for row in found.values()}


def where(tree: dict[str, dict[str, Any]], path: str) -> tuple[dict[str, Any] | None, str]:
    """The location a path is in, the longest location path in tree it starts with, and the path below it."""
    parts = [part for part in path.split('/') if part]
    for n in range(len(parts), 0, -1):
        if (location := tree.get('/'.join(parts[:n]))) is not None:
            return location, '/'.join(parts[n:])
    return None, path


class Catalog:
    """The catalog in the database at dsn, read only."""

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError("the catalog's database is required")
        self.dsn = dsn
        self.lake_ids: dict[str, int] = {}   # each location's Linked Data id -> the catalog's id for it, as locations() last read them
        self._columns: list[str] | None = None   # columns(), read once

    def _open(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, options='-c default_transaction_read_only=on', row_factory=dict_row, connect_timeout=30)

    def locations(self) -> list[dict[str, Any]]:
        """Linked Data's locations in use whose entries are in the catalog, with every location above them, so they make one tree:
        each its id, name, parent's id and, where it has entries, the catalog's id for it."""
        from .ld import Type, gppufs
        records = {r['id']: r for r in gppufs.api('GET', '/files', type=int(Type.FS_LOCATION))['items']
                   if r['status'] not in gppufs.NOT_IN_USE}
        kept: set[str] = set()
        for r in records.values():
            if 'lake_id' in r['meta']:
                while r and r['id'] not in kept:
                    kept.add(r['id'])
                    r = records.get(r['parent_id'])
        self.lake_ids = {id: records[id]['meta']['lake_id'] for id in kept if 'lake_id' in records[id]['meta']}
        return [{'id': id, 'name': records[id]['name'], 'uid': records[id]['data'].get('uid'),
                 'parent': records[id]['parent_id'] if records[id]['parent_id'] in kept else None, 'lake_id': self.lake_ids.get(id)}
                for id in kept]

    def lake_id(self, location: str) -> int:
        """The catalog's id for a location, by its Linked Data id."""
        if location not in self.lake_ids:
            self.locations()
        if location not in self.lake_ids:
            raise LookupError(f'location {location}: the catalog holds nothing there')
        return self.lake_ids[location]

    def columns(self) -> list[str]:
        """The columns an entry is described by, by their internal names: its content type, then each column SharePoint gave some
        of its items and not every one, those carried most first. Every item carries SharePoint's own columns, its file name, its
        version, who edited it; what only some carry is what a library or a content type adds, a statement's period, a tax form's
        year. Read from the whole catalog once."""
        if self._columns is None:
            with self._open() as db:
                items = db.execute(ITEMS).fetchone()['n']
                self._columns = ['ContentType'] + [row['name'] for row in db.execute(COLUMNS) if row['n'] < items]
        return self._columns

    def entries(self, location: str | None = None, parent: UUID | None = None, path: str | None = None) -> Iterator[dict[str, Any]]:
        """What is directly inside an entry, parent, at a location's root, or in the folder a path names as the desktop shows the
        catalog, by name, each with the text of its columns; read a fetch at a time from a cursor the database keeps, so a folder
        of any size is never held whole. What is asked for is found before the first row is."""
        if path is not None:
            found, below = where(paths(self.locations()), path)
            if found is None:
                raise LookupError(f'{path}: the catalog holds no location there')
            if not below and found['lake_id'] is None:
                return iter(())
            location, parent = (None, self.at(found['id'], below)) if below else (found['id'], None)
        if parent:
            with self._open() as db:
                if db.execute('SELECT 1 FROM lake.entity WHERE uid = %s', (parent,)).fetchone() is None:
                    raise LookupError(f'entry {parent}: the catalog holds no such entry')
        inside, value = ('e.parent_uid = %s', parent) if parent else ('e.location_id = %s AND e.parent_uid IS NULL', self.lake_id(location))
        columns = self.columns()

        def rows() -> Iterator[dict[str, Any]]:
            with self._open() as db, db.cursor(name='entries') as cursor:
                cursor.itersize = FETCH
                cursor.execute(ENTRIES.format(inside=inside), (value,))
                for row in cursor:
                    held = row['columns'] or {}
                    row['columns'] = {name: text for name in columns if (text := _text(held.get(name)))}
                    yield row
        return rows()

    def at(self, location: str, path: str) -> UUID:
        """The uid of the entry path names below a location's root."""
        names = [name for name in path.split('/') if name]
        if not names:
            raise LookupError(f'location {location}: an empty path names its root, which is no entry')
        with self._open() as db:
            found = db.execute(AT, {'location': self.lake_id(location), 'names': names}).fetchone()
        if found is None:
            raise LookupError(f'location {location}: the catalog holds nothing at {path}')
        return found['uid']

    def entry(self, uid: UUID) -> dict[str, Any]:
        """One entry with every instance of it, the latest first."""
        with self._open() as db:
            found = db.execute(ENTRY, (uid,)).fetchone()
        if found is None:
            raise LookupError(f'entry {uid}: the catalog holds no such entry')
        return found


def api(catalog: Catalog):
    """catalog as REST resources, a FastAPI app an APIApp serves at /lake/catalog, mounted before the Lake's at /lake, whose paths
    are uris and would take it. Needs FastAPI (the `ld` extra).

    GET /locations                  Linked Data's locations whose entries are in the catalog, as one tree
    GET /locations/{id}/entries     what is at a location's root, a line of JSON each, by name
    GET /locations/{id}/entry?path= the entry path names below a location's root
    GET /entries/{uid}              one entry with every instance of it
    GET /entries/{uid}/entries      what is directly inside an entry, a line of JSON each, by name
    GET /entries?path=              what is directly inside the folder path names as the desktop shows the catalog, a line each
    GET /columns                    the columns an entry is described by, each its internal name and its name in words

    An entry listed carries the text of its columns. What the catalog does not hold answers 404 with its error."""
    from fastapi import FastAPI, Response
    from fastapi.responses import StreamingResponse

    def reply(payload: Any, status: int = 200) -> Response:
        return Response(json.dumps(payload, default=_json, ensure_ascii=False), status_code=status, media_type='application/json; charset=utf-8')

    def lines(rows: Iterator[dict[str, Any]]) -> StreamingResponse:
        return StreamingResponse((json.dumps(row, default=_json, ensure_ascii=False) + '\n' for row in rows),
                                 media_type='application/x-ndjson; charset=utf-8')   # as a client takes text without one differs

    app = FastAPI(title='Catalog')
    app.add_exception_handler(LookupError, lambda request, error: reply({'error': str(error)}, 404))

    @app.get('/locations')
    def locations():
        return reply(catalog.locations())

    @app.get('/locations/{id}/entries')
    def at_root(id: str):
        return lines(catalog.entries(location=id))

    @app.get('/locations/{id}/entry')
    def entry_at(id: str, path: str):
        return reply(catalog.entry(catalog.at(id, path)))

    @app.get('/entries/{uid}')
    def entry(uid: UUID):
        return reply(catalog.entry(uid))

    @app.get('/entries/{uid}/entries')
    def inside(uid: UUID):
        return lines(catalog.entries(parent=uid))

    @app.get('/entries')
    def at_path(path: str):
        return lines(catalog.entries(path=path))

    @app.get('/columns')
    def columns():
        return reply([{'name': name, 'label': label(name)} for name in catalog.columns()])

    return app


def _seconds(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


class CatalogFileSystem(AbstractFileSystem):
    """The catalog through its API, an fsspec filesystem: Linked Data's locations are folders, each under the one above it, and in
    each is what the catalog holds at its root. ls reads a folder a line at a time and keeps what it read, which info answers from;
    an entry is shown modified when its source last changed it and created when its source says it was, SharePoint's Created.
    Read-only, and without bytes: the catalog holds what an entry is, not its content. client is the API's, made from url, or one a
    caller gives, such as a test's."""

    protocol = 'catalog'
    cachable = False

    def __init__(self, url: str = '', client: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        import httpx
        self.client = client or httpx.Client(base_url=url.rstrip('/'), timeout=300)   # as gppu.ld.gppufs.connect gives each call
        self._tree: dict[str, dict[str, Any]] | None = None   # Linked Data's locations by path, read once
        self._listed: dict[str, dict[str, dict[str, Any]]] = {}   # each folder listed -> its entries by name

    def _get(self, route: str, **params: str):
        r = self.client.get(f"/lake/catalog{route}", params=params)
        if r.status_code == 404:
            raise FileNotFoundError(f'{route}: {r.text}')
        r.raise_for_status()
        return r

    def _locations(self) -> dict[str, dict[str, Any]]:
        """Linked Data's locations by path, read once."""
        if self._tree is None:
            self._tree = paths(self._get('/locations').json())
        return self._tree

    def _where(self, path: str) -> tuple[dict[str, Any] | None, str]:
        return where(self._locations(), path)

    @staticmethod
    def _entry(row: dict[str, Any], name: str) -> dict[str, Any]:
        """A catalog row as fsspec has an entry; its uid is `id`, since a FUSE bridge reads `uid` as the owner's."""
        folder = row['kind'] == 'folder'
        entry = {'name': name, 'type': 'directory' if folder else 'file', 'size': 0 if folder else row['size'] or 0,
                 'id': row['id'], 'content_type': row['content_type'], 'columns': row['columns']}
        for key, value in (('mtime', row['modified']), ('ctime', row['created'])):
            if value:
                entry[key] = _seconds(value)
        return entry

    def ls(self, path: str = '', detail: bool = True, **kwargs: Any) -> list[dict[str, Any]] | list[str]:
        path = self._strip_protocol(path).strip('/')
        location, below = self._where(path)
        rows = [{'name': key, 'type': 'directory', 'size': 0} for key in self._locations()
                if key.rpartition('/')[0] == path and key != path]
        if location is not None and (below or location['lake_id'] is not None):
            route = f"/entries/{self._id(path, location, below)}/entries" if below else f"/locations/{location['id']}/entries"
            listed = {}
            with self.client.stream("GET", f"/lake/catalog{route}") as r:
                if r.status_code == 404:
                    raise FileNotFoundError(f'{route}: {r.read().decode()}')
                r.raise_for_status()
                for line in r.iter_lines():
                    row = json.loads(line)
                    listed[row['name']] = self._entry(row, f"{path}/{row['name']}")
            self._listed[path] = listed
            rows += listed.values()
        elif location is None and path:
            raise FileNotFoundError(path)
        return rows if detail else [row['name'] for row in rows]

    def _id(self, path: str, location: dict[str, Any], below: str) -> str:
        """The uid of the entry at path, below in location: from its folder's listing once it was listed, else the catalog
        resolves it."""
        folder, _, name = path.rpartition('/')
        if name in self._listed.get(folder, {}):
            return self._listed[folder][name]['id']
        return self._get(f"/locations/{location['id']}/entry", path=below).json()['id']

    def info(self, path: str = '', **kwargs: Any) -> dict[str, Any]:
        path = self._strip_protocol(path).strip('/')
        if not path or path in self._locations():
            return {'name': path, 'type': 'directory', 'size': 0}
        folder, _, name = path.rpartition('/')
        if folder not in self._listed:
            self.ls(folder)
        if name not in self._listed[folder]:
            raise FileNotFoundError(path)
        return self._listed[folder][name]

    def _open(self, path: str, mode: str = 'rb', **kwargs: Any):
        raise PermissionError(f'{path}: the catalog holds what an entry is, not its content')
