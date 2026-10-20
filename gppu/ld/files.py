"""Linked Data's files API: the file systems Alex runs, as gppufs (gppu.fs) reads and configures them (_Projects/Linked Data,
"Linked Data - Universal types, statuses and sharding", # File system; "Linked Data - gppufs"). Separate from the core and built on
it (gppu.ld), beside gppufs; served at /ld/v1/files, documented at /ld/v1/files/docs.

Linked Data holds what gppufs is configured with and where its indexes are; the files are in gppufs's indexes, not in records. The
file system is 0x20-0x2F: an FS node is the base of every file system type, an FS location a place files are reached, an FS file
one file as a single thing wherever its copies are, an FS index a pointer to one gppufs index. Each is created, read, updated and
searched at `/files`, and `GET /files/locations` gives the locations in use as rows of gppufs's configuration table, which
`gppu.fs.GppuCatalog` is made from; `GET /files/address` finds the location an address is in, `GET /files/{id}/files` lists what a
location holds. Credentials are not stored: a Provider reads them where it declares them."""
from uuid import UUID

import pydantic
from fastapi import APIRouter, HTTPException
from sqlmodel import or_, select

from . import Db, RecordFields, Resource, Stored, Type, api_at, listed, typed

NOT_IN_USE = ('discarded', 'rejected', 'archived')   # the statuses of a location not in use (# States)


class FSNode(RecordFields, Stored, table=True):
    """The base of every file system type. Path: `/files`, with the others."""
    __tablename__ = 'fs_node'


class FSLocation(RecordFields, Resource, Stored, table=True):
    """A place files are reached: a connection and a path, gppufs's `Location`. A root location is its connection and its Provider,
    its connection's parameters in `data.handler`, and has no parent; every other location is inside the location above it.
    `data.uid` is its gppufs uid, `data.canonical` its canonical uri, and the rest of `data` its configuration as gppufs has it.
    `subtype`: `logical` or `physical`."""
    __tablename__ = 'fs_location'
    PARENTS = (Type.FS_LOCATION,)


class FSFile(RecordFields, Stored, table=True):
    """One file as a single thing, wherever its copies are: a collection. The copies are in gppufs's indexes; the FS file is what
    other records refer to."""
    __tablename__ = 'fs_file'


class FSIndex(RecordFields, Resource, Stored, table=True):
    """A pointer to one gppufs index: the SQLite file beside a location, or inside an archive, holding what a walk read of every
    file there."""
    __tablename__ = 'fs_index'


class Configured(pydantic.BaseModel):
    """A location as a row of gppufs's configuration table (gppu.fs.GppuCatalog): its `data` with its uid, canonical uri, name, parent
    and connection, where gppufs reads them."""
    model_config = pydantic.ConfigDict(extra='allow')   # the rest of its data as configuration has it: path, service, kind, icon, folders, ...
    id: UUID = pydantic.Field(description="The location's record.")
    uid: str = pydantic.Field(description='Its gppufs uid, from configuration: `data.uid`.')
    canonical: str = pydantic.Field(description='Its canonical uri: `data.canonical`.')
    name: str | None = pydantic.Field(description="Its name: the record's `name`.")
    parent: str | None = pydantic.Field(description='The uid of the location above it, none for a root location.')
    connection: str = pydantic.Field(description='The connection its Provider is constructed with: the uid of its root location, which is its connection.')
    handler: dict | None = pydantic.Field(None, description="A root location's connection parameters, `data.handler`, without credentials: gppufs's `connections` table by `connection`.")
    tags: list[str] | None = pydantic.Field(None, description='Its tags: `meta.tags`.')


routes = APIRouter(tags=['file'])


@routes.get('/files/locations', response_model=list[Configured], summary='List the locations as gppufs reads them')
async def locations(db: Db):
    """Every location in use that has a uid and a canonical uri, the two a gppufs Location is known and reached by, as a row of
    gppufs's configuration table: one not discarded, rejected or archived, inside locations that are in use too, since a location is
    part of the location above it. A location always has a connection: its root location, whose `data.handler` holds the connection's
    parameters, so gppufs's catalog is made from these rows and their handlers:
    `GppuCatalog({'locations': rows, 'connections': {r['uid']: r['handler'] for r in rows if r['handler']}})`."""
    in_use = select(FSLocation).where(or_(FSLocation.status.is_(None), FSLocation.status.not_in(NOT_IN_USE)))
    rows = {r.id: r for r in (await db.exec(in_use)).all() if r.data.get('uid') and r.data.get('canonical')}

    def root(r: FSLocation) -> FSLocation | None:
        """The root location above it; none when one above it is not a row here, so it is not in use either."""
        while r.parent_id:
            if not (r := rows.get(r.parent_id)):
                return None
        return r
    return [r.data | {'id': r.id, 'name': r.name, 'parent': r.parent_id and rows[r.parent_id].data['uid'], 'connection': top.data['uid']}
            | ({'tags': r.meta['tags']} if 'tags' in r.meta else {}) for r in rows.values() if (top := root(r))]


class Addressed(pydantic.BaseModel):
    """Where an address is: the location in use that holds it, and the rest of the address inside the location."""
    location: Configured = pydantic.Field(description="The location, as a row of gppufs's configuration table.")
    path: str = pydantic.Field(description='The rest of the address inside it, empty for the location itself.')


@routes.get('/files/address', response_model=Addressed, summary='Find the location an address is in')
async def address(db: Db, uri: str):
    """The location in use whose canonical uri or uid is the longest start of `uri`, a whole segment, and the rest of the address
    inside it: the location gppufs reads that file or folder from. 404 when no location in use holds it."""
    best = None
    for row in await locations(db):
        for start in (row['canonical'], row['uid']):
            if (uri == start or uri.startswith(start.rstrip('/') + '/')) and (not best or len(start) > len(best[1])):
                best = (row, start)
    if not best:
        raise HTTPException(404, f'no location in use holds {uri}')
    return Addressed(location=best[0], path=uri[len(best[1]):].strip('/'))


@routes.get('/files/{id}/files', response_model=list[FSNode], summary="List what a location holds")
async def contents(db: Db, id: UUID):
    """A `list`: the file system records whose parent it is, the locations inside a location among them, by name, each with the
    columns of an FS node. What a location's files are is in gppufs's index beside them, not here."""
    await FSNode.read(db, id)
    return await listed(db, select(FSNode).where(FSNode.parent_id == id).order_by(FSNode.name, FSNode.id), f'file system records are under {id}')


app = api_at('/files', 'files', 'The file systems as gppufs reads and configures them: their locations, files and indexes.',
             routes, typed('/files', RecordFields, 'file', FSNode, FSLocation, FSFile, FSIndex))   # /files/locations before /files/{id}, which would take its word
