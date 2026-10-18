"""Linked Data's files API: the file systems Alex runs, as gppufs (gppu.fs) reads and configures them, every object a `file` whose
`subtype` says which (_Conventions/Linked Data.md, # File System; # API ## Types; Linked Data/Files.md). Separate from the core and
built on it (gppu.ld), beside gppufs; served at /ld/v1/files, documented at /ld/v1/files/docs.

gppufs is how Alex's tools reach files: FileIndexer, admin_ui's locations, the Lake's jobs. A Location is one place in its
configuration, known by its uid and its canonical uri, reached through the Provider of its uri's scheme constructed with a
connection; a Container lists what is below a Location, its handlers read what each entry is, and an index keeps what they read.
This API keeps both sides:
- the configuration: `GET /files/locations`, the locations as gppufs's configuration table, each a location record whose `data.handler`
  is its connection, the parameters its Provider is constructed with (Alex: "handler connection parameters are stored in
  [[Linked Data#Location]]"); `gppu.fs.GppuCatalog` is made from them. Credentials are not stored: a Provider reads them where it
  declares them;
- the index: the containers, folders, files and archives below a location (`/files`, its children by `parent_id`), a folder's
  contents written in one call (`PUT /files`), an address resolved to its record (`GET /files/address`) and a record to its address
  (`GET /files/{id}/address`), what a location or a folder holds (`GET /files/{id}/totals`); and a location's FileIndexer runs
  (`/files/runs`)."""
from datetime import datetime
from typing import Literal
from urllib.parse import quote, unquote
from uuid import UUID

import pydantic
from fastapi import APIRouter, HTTPException
from sqlalchemy import BigInteger, DateTime, String, cast, column, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from . import Activity, ActivityFields, Db, RecordFields, Span, Stored, Type, api_at, listed, saved, typed

ABANDONED = 'abandoned'   # the status of a record no longer in use: the core deletes only links, so anything else that goes is kept with this status (Linked Data.md, # API ## Storage)
DELETED = 'deleted'   # the status of a file its folder no longer holds, which FileIndexer sets (Linked Data.md, # API ## Types); the store keeps it
SUBTYPES = {   # what a file is (Linked Data/Files.md, # Subtypes): gppufs's Location, the Containers it lists and the entries its walk tells apart
    'location': 'where files are, from configuration: `data.uid` its gppufs uid, `data.canonical` its canonical uri, `data.handler` its connection; its parent a location, or none',
    'container': 'a share of a location, such as an SMB share; its parent the location',
    'folder': 'a folder; its parent a location, a container, a folder, a git repository or an archive',
    'file': 'a file; it holds nothing',
    'archive': 'a ZIP, RAR or tar.gz file, its members its children; the format in `data.format`',
    'git': 'a folder that is a git repository, its listing holding `.git`; what git says of it in `data.git`, where gppufs read it',
    'ignored': 'a folder or file an ignore rule matched, or a link: listed, never entered; the rule in `meta.ignored_reason`, a link `meta.boundary` and `meta.target`',
    'system': 'a folder with the system attribute: listed, never entered',
}
Subtype = Literal[*SUBTYPES]   # the API takes no other; Postgres does not check it
FOLDERS = ('folder', 'git', 'ignored', 'system')   # the folders a location or a folder holds, as FileIndexer counts them
FILES = ('file', 'archive')   # its files


class FileFields(RecordFields):
    """A file as a caller sends it: create sends its fields, update sends what changes."""
    subtype: Subtype | None = Field(None, sa_type=String, description='What the file is: ' + '; '.join(f'`{k}` {v}' for k, v in SUBTYPES.items()) + '.')


class Entry(FileFields):
    """A file as a caller sends it among a folder's contents: with the `id` of a file that is there it is merged into it, without one it is created."""
    id: UUID | None = Field(None, description='The file it updates, or the id it is created with; none for a new file.')


class File(FileFields, Stored, table=True):
    """A file-system object, its `subtype` saying which; its parent is a file. Path: `/files`. Written keeping what Postgres does not
    (Files.md). An insert is an upsert (Linked Data.md, Operations): a file sent without an `id` where one is, its parent and name the
    table's own unique pair, is merged into it. A location's `data.uid` names one location: a write that gives a location, not abandoned,
    the uid another such location holds is refused; locations that shared a uid before the rule are written as they are."""

    @classmethod
    async def write(cls, db: AsyncSession, id: UUID | None, sent: SQLModel) -> 'File':
        def uid(r):   # the uid a file holds as a location, none when it is not one or is abandoned
            return r.data.get('uid') if r.subtype == 'location' and r.status != ABANDONED else None
        if not id and sent.parent_id and sent.name is not None:   # the file already where it is put, if one is
            id = await db.scalar(select(File.id).where(File.parent_id == sent.parent_id, File.name == sent.name))
        held = await db.get(cls, id) if id else None
        before = uid(held) if held else None   # read before the write replaces its data
        row = await super().write(db, id, sent)
        if (given := uid(row)) and given != before:
            await db.flush()   # the row's id, and what the call wrote before it
            if await db.scalar(select(func.count()).where(File.subtype == 'location', File.data['uid'].astext == given, File.id != row.id,
                                                          or_(File.status.is_(None), File.status != ABANDONED))):
                raise HTTPException(422, f'the uid {given} names another location')
        return row


class Configured(pydantic.BaseModel):
    """A location as a row of gppufs's configuration table (gppu.fs.GppuCatalog): its `data` with its uid, canonical uri, name, parent
    and connection, where gppufs reads them."""
    model_config = pydantic.ConfigDict(extra='allow')   # the rest of its data as configuration has it: path, service, kind, icon, folders, ...
    id: UUID = pydantic.Field(description="The location's record.")
    uid: str = pydantic.Field(description='Its gppufs uid, from configuration: `data.uid`.')
    canonical: str = pydantic.Field(description='Its canonical uri: `data.canonical`.')
    name: str | None = pydantic.Field(description="Its name: the record's `name`.")
    parent: str | None = pydantic.Field(description="The uid of the location above it, none at the top: its parent's, when that is a row of this table.")
    connection: str | None = pydantic.Field(description='The connection its Provider is constructed with: its own uid when it has a `handler`, none when it has not.')
    handler: dict | None = pydantic.Field(None, description="Its connection's parameters, `data.handler`, without credentials: gppufs's `connections` table by `connection`.")
    tags: list[str] | str | None = pydantic.Field(None, description='Its tags: `meta.tags`, or as its data has them.')


class Totals(pydantic.BaseModel):
    """What a location or a folder holds, its whole subtree, as FileIndexer shows them."""
    folders: int = pydantic.Field(description='Its folders: ' + ', '.join(f'`{s}`' for s in FOLDERS) + '.')
    files: int = pydantic.Field(description='Its files: ' + ', '.join(f'`{s}`' for s in FILES) + '.')
    bytes: int = pydantic.Field(description="Its files' bytes, `meta.size`.")
    span: Span | None = pydantic.Field(description="When its files were last changed, the earliest and the latest `meta.modified_at`; none without them.")
    seen: datetime | None = pydantic.Field(description='When the latest of it was seen, `meta.last_seen`.')
    notes: int = pydantic.Field(description='Its notes: its files named `.md`.')
    sessions: int = pydantic.Field(description='Its sessions: the session fingerprints its handlers read, `data.fingerprints`, each once.')


class Addressed(FileFields, Stored):
    """A file with where it is, calculated from its parents and not stored (Linked Data/Files.md, # Calculated)."""
    type: Type | None = Field(None, description='What the record is: the first byte of its `id`.')
    location_id: UUID = Field(description='_location_: the location above it; a location is its own.')
    path: str = Field(description='_path_: the names from its location down to it, `/` between them; empty for a location.')
    address: str = Field(description="_address_: its location's canonical uri with its path below it, each name uri-escaped, as gppufs addresses it.")


def below(canonical: str, uri: str) -> str | None:
    """The escaped path a uri names below a canonical uri, empty for the canonical uri itself; none when the uri is not at or below it.
    A canonical uri that is a scheme's root (`work://`) has its paths right after it, as gppufs reads them."""
    if canonical.endswith('://'):
        return uri[len(canonical):].strip('/') if uri.startswith(canonical) else None
    root = canonical.rstrip('/')
    if uri.rstrip('/') == root:
        return ''
    return uri[len(root) + 1:].rstrip('/') if uri.startswith(root + '/') else None


def address(canonical: str, path: str) -> str:
    """The address of a path below a canonical uri: each name uri-escaped, as gppufs's Location.uri_of writes it."""
    if not path:
        return canonical
    return canonical + quote(path, safe='/') if canonical.endswith('/') else f'{canonical}/{quote(path, safe="/")}'


async def in_use(db: AsyncSession) -> list[File]:
    """The locations in use: an abandoned location holds nothing."""
    return (await db.exec(select(File).where(File.subtype == 'location', or_(File.status.is_(None), File.status != ABANDONED)))).all()


async def addressed(db: AsyncSession, row: File) -> Addressed:
    """A file with its location, path and address: its parents read up to the location above it."""
    names, at = [], row
    while at.subtype != 'location':
        names.append(at.name)
        if not at.parent_id or not (at := await db.get(File, at.parent_id)):
            raise HTTPException(422, f'{row.id} has no location above it')
    if not (canonical := at.data.get('canonical')):
        raise HTTPException(422, f'{at.id}, the location above {row.id}, has no canonical uri')
    path = '/'.join(reversed(names))
    return Addressed.model_validate(row, update={'location_id': at.id, 'path': path, 'address': address(canonical, path)})


routes = APIRouter(tags=['file'])


@routes.get('/files/locations', response_model=list[Configured], summary='List the locations as gppufs configures them')
async def locations(db: Db):
    """Every location in use that has a uid and a canonical uri, the two a gppufs Location is known and reached by, as a row of
    gppufs's configuration table; the other locations are at `/files` by `filters` on `subtype`. A location's connection is its own
    `data.handler`, named by its uid, so gppufs's catalog is made from these rows and their handlers:
    `GppuCatalog({'locations': rows, 'connections': {r['uid']: r['handler'] for r in rows if r['connection']}})`."""
    rows = [r for r in await in_use(db) if r.data.get('uid') and r.data.get('canonical')]
    uids = {r.id: r.data['uid'] for r in rows}
    return [r.data | {'id': r.id, 'name': r.name, 'parent': uids.get(r.parent_id), 'connection': r.data['uid'] if r.data.get('handler') else None}
            | ({'tags': r.meta['tags']} if 'tags' in r.meta else {}) for r in rows]


@routes.get('/files/address', response_model=Addressed, summary='Read a file by its address')
async def at(db: Db, uri: str):
    """The file an address names: the location in use whose canonical uri begins it for longest, then each name below it, a child of
    the one before. 404 when nothing is stored there, 422 when two locations begin it equally long. A file its folder no longer holds is
    still there, its `status` `deleted`."""
    held = [(r, rest) for r in await in_use(db) if (c := r.data.get('canonical')) and (rest := below(c, uri)) is not None]
    deepest = [(r, rest) for r, rest in held if len(r.data['canonical']) == max(len(h.data['canonical']) for h, _ in held)]
    if len(deepest) != 1:
        raise HTTPException(422 if deepest else 404, f"{len(deepest)} locations hold {uri}{': ' + ', '.join(str(r.id) for r, _ in deepest) if deepest else ''}")
    row, rest = deepest[0]
    for name in (unquote(n) for n in rest.split('/') if rest):
        if not (row := (await db.exec(select(File).where(File.parent_id == row.id, File.name == name))).first()):
            raise HTTPException(404, f'nothing is stored at {uri}: {name} is not under its folder')
    return await addressed(db, row)


@routes.get('/files/{id}/files', response_model=list[File], summary="List a folder's files")
async def contents(db: Db, id: UUID):
    """`list`, a simple select of like records (Linked Data.md, Operations): the files in a folder or a location, by name, as the table
    keeps them under it. No query, that is search, and not paged: more than a list sends (gppu.ld's `listed`) is refused with their
    count and size, and search pages them, `filters` on `parent_id`."""
    return await listed(db, select(File).where(File.parent_id == id).order_by(File.name), f'files are in {id}')


@routes.get('/files/{id}/address', response_model=Addressed, summary="Read a file's address")
async def address_of(db: Db, id: UUID):
    """The file with its location, path and address, read from its parents. 404 when there is none."""
    return await addressed(db, await File.read(db, id))


@routes.get('/files/{id}/totals', response_model=Totals, summary='Read what a location or a folder holds')
async def totals(db: Db, id: UUID, own: bool = False):
    """Its whole subtree, read down its children but for what its folder no longer holds (`deleted`) and what is no longer in use
    (`abandoned`), the locations below it with what they hold, or with `own` only what it holds itself: its folders and files,
    their bytes and times, its notes and sessions, and when the latest of it was seen. 404 when there is none."""
    await File.read(db, id)
    held = File.status.not_in((DELETED, ABANDONED)) | File.status.is_(None)
    if own:
        held &= File.subtype.is_distinct_from('location')
    under = select(File.id, File.subtype, File.name, File.data, File.meta).where(File.parent_id == id, held).cte('under', recursive=True)
    under = under.union_all(select(File.id, File.subtype, File.name, File.data, File.meta).join(under, File.parent_id == under.c.id).where(held))
    file, time = under.c.subtype.in_(FILES), cast(under.c.meta['modified_at'].astext, DateTime(timezone=True))
    folders, files, size, first, last, seen, notes = (await db.execute(select(
        func.count().filter(under.c.subtype.in_(FOLDERS)), func.count().filter(file),
        func.coalesce(func.sum(cast(under.c.meta['size'].astext, BigInteger)).filter(file), 0), func.min(time).filter(file),
        func.max(time).filter(file), func.max(cast(under.c.meta['last_seen'].astext, DateTime(timezone=True))),
        func.count().filter(file & under.c.name.ilike('%.md'))))).one()
    fingerprint = func.jsonb_array_elements(under.c.data['fingerprints']).table_valued(column('value', JSONB)).alias('fingerprint')
    sessions = await db.scalar(select(func.count(func.distinct(fingerprint.c.value[1].astext))).select_from(under)
                                    .join(fingerprint, true()).where(fingerprint.c.value[0].astext == 'session'))
    return Totals(folders=folders, files=files, bytes=size, span=Span(start=first, end=last) if first else None, seen=seen,
                  notes=notes, sessions=sessions)


@routes.put('/files', response_model=list[File], summary="Update a folder's contents")
async def update(db: Db, records: list[Entry]):
    """Many files in one call, as FileIndexer writes what it compared a folder with: the folder itself, what it holds, found again
    with the `id` it is stored under and merged into it, or new and created; a file the folder no longer holds is sent with its
    `id` and the `status` `deleted`, and the store keeps it. They come back in the order sent; when one is refused, none is written."""
    (await db.exec(select(File).where(File.id.in_([r.id for r in records if r.id])))).all()   # what is there, read at once
    rows = [await File.write(db, r.id, r) for r in records]
    return await saved(db, rows)


app = api_at('/files', 'files', 'The file systems as gppufs reads and configures them: locations, containers, folders, files, archives, '
             "and a location's FileIndexer runs.",
             typed('/files/runs', Activity, ActivityFields, 'run'),   # before /files, whose /{id} would take its word
             routes, typed('/files', File, FileFields, 'file'))
