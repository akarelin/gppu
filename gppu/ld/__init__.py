"""Linked Data: records and the links between them, on Postgres, and what an API of a type is built from (_Conventions/Linked Data.md,
# API). The basic types' tables (`Record`, `Node`, `Event`, `Activity`, `Link`), the rules a record is written by on its class
(`Stored.write`), the core's paths (`app`: `/types`, `/records`, `/links`), and for an API of its own for a type: `typed()`, a type's
create, read, update and search; `listed()` and `paged()`, its lists and pages; `api_at()`, the API with its own documentation; `served()`,
the APIs at one address. The tables are made by the store's `schema.sql` (RAN `Projects/ld`); `connect()` opens the store.

Needs the `ld` extra, and fastapi-querybuilder installed with `--no-deps`: its metadata lists poetry, uvicorn and aiosqlite as runtime
dependencies."""
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Annotated, Any, Literal, Self, TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_pagination import add_pagination, create_page
from fastapi_pagination.cursor import CursorPage   # a page carries the cursor of the next one (sqlakeyset reads after the last row)
from fastapi_pagination.customization import (CustomizedPage, UseExcludedFields, UseFieldsAliases, UseIncludeTotal, UseName,
                                              UseOptionalParams, UseParamsFields)
from fastapi_pagination.ext.sqlalchemy import apaginate   # querybuilder builds SQLAlchemy selects
from fastapi_querybuilder import QueryBuilder, QueryParams, build_query
from psycopg.errors import UndefinedFunction
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, field_validator, model_validator
from sqlakeyset import custom_bookmark_type
from sqlalchemy import DateTime, FetchedValue, SmallInteger, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, Range
from sqlalchemy.exc import DataError, IntegrityError, NoResultFound, StatementError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.elements import UnaryExpression
from sqlalchemy.sql.visitors import iterate
from sqlmodel import Column, Field, SQLModel, delete, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

T = TypeVar('T')

engine = None   # the store, opened by connect()
DAY, SECOND = timedelta(days=1), timedelta(seconds=1)
LIST = 1000   # the most records a list sends: the older data's largest list of like records is a folder's 585 files (work 15, a location's runs 16, 2026-10-17)
LIST_BYTES = 1_000_000   # and the most data it sends, `data` and `meta` as Postgres stores them: that folder's are 187 kB (work 45 kB; a session's messages up to 145 MB, so they are read a page at a time)
DATETIME, DURATION = TypeAdapter(datetime), TypeAdapter(timedelta)


def connect(dsn: str):
    """The store at `dsn`, `postgresql+psycopg://user:password@host:port/database`; a filter's time is read without its zone, so
    compared as UTC."""
    global engine
    engine = create_async_engine(dsn, connect_args={'options': '-c timezone=UTC'})


async def database():
    """A database session per request, not a Linked Data session."""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        yield db

Db = Annotated[AsyncSession, Depends(database)]

Page = CustomizedPage[CursorPage[T], UseName('Page'), UseIncludeTotal(True), UseOptionalParams(),
                      UseParamsFields(size=Query(None, ge=1, alias='limit', description='How many records a page holds.')),
                      UseExcludedFields('current_page', 'current_page_backwards'),
                      UseFieldsAliases(next_page='next', previous_page='previous')]   # `limit` records after `cursor`, the total, and `next`
Params = Page.__params_type__
LEAST = {str: '', int: 0, UUID: UUID(int=0), datetime: datetime.min.replace(tzinfo=ZoneInfo('UTC'))}   # what an empty column is sorted as


def sort_key(key):
    """A sort key a page can read after: one over a column a record may leave empty sorts that record as the column's least value."""
    column = next(c for c in iterate(key.element) if isinstance(c, Column))   # under querybuilder's lower() of a text column
    return UnaryExpression(func.coalesce(key.element, LEAST[column.type.python_type]), modifier=key.modifier) if column.nullable else key


async def listed(db: AsyncSession, query, what: str) -> list:
    """A `list` (Linked Data.md, Operations), not paged: every row the query selects, in its order, refused with 422 naming their count
    and size when they are more than a list sends, `LIST` rows or `LIST_BYTES` of their `data` and `meta` as stored."""
    held = query.order_by(None).subquery()
    n, size = (await db.exec(select(func.count(), func.coalesce(func.sum(func.pg_column_size(held.c.data) + func.pg_column_size(held.c.meta)), 0)))).one()
    if n > LIST or size > LIST_BYTES:
        raise HTTPException(422, f'{n} {what}, {size} bytes of data, more than a list sends ({LIST}, {LIST_BYTES} bytes): search them, a page at a time')
    return (await db.exec(query)).all()


async def paged(db: AsyncSession, query, model, params):
    """A page of a search: `limit` records after the last one of the page before (sqlakeyset), so the order ends with the id, which no
    two rows share, and its keys are ones a page can read after. Every match when no limit is given."""
    keys = [sort_key(k) for k in query._order_by_clauses]   # querybuilder's sort, read as sqlakeyset reads it
    query = query.order_by(None).order_by(*keys, model.id)
    if params.size is None:
        rows = (await db.scalars(query)).all()   # querybuilder's select is SQLAlchemy's: rows of one record each
        return create_page(rows, params=params, total=len(rows))
    return await apaginate(db, query, params=params)


async def saved[M](db: AsyncSession, row: M) -> M:
    """The row, with what the call wrote, committed together."""
    await db.commit()
    return row


class Type(IntEnum):
    """What a record is: the first byte of its `id`. The store's `record_types` holds the same codes (`types_agree`)."""
    RECORD = 0x01
    NODE = 0x02
    EVENT = 0x10
    ACTIVITY = 0x11
    FILE = 0x20
    SESSION = 0x30
    MESSAGE = 0x31
    WORK = 0x40
    LINK = 0xA0


def nul_free(v: Any) -> Any:
    """Postgres' text and jsonb cannot hold U+0000, so it is dropped wherever it is sent; it reaches a session's messages in UTF-16 output read as bytes."""
    if isinstance(v, str):
        return v.replace('\x00', '')
    if isinstance(v, dict):
        return {nul_free(k): nul_free(x) for k, x in v.items()}
    if isinstance(v, list):
        return [nul_free(x) for x in v]
    return v


class RecordFields(SQLModel):
    """A record as a caller sends it: create sends its fields, update sends what changes. A field it does not have is refused."""
    model_config = ConfigDict(extra='forbid')
    # String, not SQLModel's own AutoString: search looks for its text only in String columns
    subtype: str | None = Field(None, sa_type=String, description='Plain text refining the `type`, from a short list per type that Postgres does not enforce.')
    status: str | None = Field(None, sa_type=String, description='Plain text, its values per type.')
    name: str | None = Field(None, sa_type=String, description='Name used for display.')
    data: dict = Field(default_factory=dict, sa_type=JSONB, description='What the record says about the thing. On update, merged into what is there; a null removes a key.')
    meta: dict = Field(default_factory=dict, sa_type=JSONB, description='How the record came to be: who made it, from what, when it was seen. `meta.tags`: a list of strings, or one string. Merged on update as `data` is.')
    parent_id: UUID | None = Field(None, description='The record it is a child of. A new `parent_id` is a move.')

    @model_validator(mode='before')
    @classmethod
    def storable(cls, v: Any) -> Any:
        return nul_free(v)


class LinkFields(RecordFields):
    """A link between two nodes as a caller sends it. Its `subtype` is empty for an edge (two-way), or the arc's direction: `outgoing`, `incoming`, `up`, `down`, `next`, `prev`."""
    from_id: UUID | None = Field(None, description="The node that made the link; an arc's direction is read from it.")
    to_id: UUID | None = Field(None, description='The node at the other end.')


class Span(BaseModel):
    """A span of time in one of the spec's forms: `start` and `end`, [start, end]; `date` and `duration` (ISO 8601, or seconds),
    [date, date + duration]; a `date` alone, [date, date + 1 day); a `ts` alone, [ts, ts + 1 second). `bounds` says which ends it holds.
    A time without a zone is UTC, as the store holds it. Not gppu's `Span` and `TimeSpan`, which have no bounds and refuse an open end."""
    start: datetime | None = None
    end: datetime | None = None
    bounds: Literal['[]', '[)'] = '[]'

    @model_validator(mode='before')
    @classmethod
    def forms(cls, v: Any) -> Any:
        if not isinstance(v, dict) or not {'date', 'ts'} & v.keys():
            return v
        if 'ts' in v:
            start, length, bounds = DATETIME.validate_python(v['ts']), SECOND, '[)'
        elif 'duration' in v:
            start, length, bounds = DATETIME.validate_python(v['date']), DURATION.validate_python(v['duration']), '[]'
        else:
            start, length, bounds = DATETIME.validate_python(v['date']), DAY, '[)'
        return {'start': start, 'end': start + length, 'bounds': bounds}

    @field_validator('start', 'end')
    @classmethod
    def utc(cls, t: datetime | None) -> datetime | None:
        return t.replace(tzinfo=ZoneInfo('UTC')) if t and not t.tzinfo else t   # Postgres takes a range of times without a zone for a tsrange, not a span


class SpanColumn(TypeDecorator):
    """A span as Postgres holds it: a tstzrange with the span's bounds. A filter's value is a span in one of the spec's forms, or a
    time, that second; Postgres orders spans by their start, then their end."""
    impl = TSTZRANGE
    cache_ok = True

    def process_bind_param(self, span, dialect):
        if span is None:
            return None
        if not isinstance(span, Span):
            span = Span.model_validate(span if isinstance(span, dict) else {'ts': span})
        return Range(span.start, span.end, bounds=span.bounds)

    def process_result_value(self, value, dialect):
        return None if value is None else Span(start=value.lower, end=value.upper, bounds=value.bounds)


custom_bookmark_type(Span, 'span', deserializer=Span.model_validate_json, serializer=Span.model_dump_json)   # a page sorted by span carries one in its cursor


class EventFields(RecordFields):
    """An event as a caller sends it: a thing that happened, and when."""
    ts: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'nullable': False}, description='When it happened.')


class ActivityFields(RecordFields):
    """An activity as a caller sends it: a named span of time."""
    span: Span | None = Field(None, sa_type=SpanColumn, sa_column_kwargs={'nullable': False}, description='When it went on: `start` and `end`; `date` and `duration`; a `date` alone, one day; a `ts` alone, one second.')


class Fields(EventFields, ActivityFields):
    """A record as a caller sends it to `/records`: a record's fields, an event's `ts`, an activity's `span`; each type takes those its table has."""


class TypeCode(TypeDecorator):
    """A record's `type` as Postgres computes it from the `id` (schema.sql), read as the `Type` it names."""
    impl = SmallInteger
    cache_ok = True

    def process_result_value(self, value, dialect):
        return None if value is None else Type(value)


class Stored(SQLModel):
    """The columns the store fills in, and how a record is written and read. A table is named by its class, its type by its table."""
    __mapper_args__ = {'eager_defaults': True}   # the id, type and times the table makes come back with the insert
    id: UUID | None = Field(None, primary_key=True, sa_column_kwargs={'server_default': FetchedValue()},
                            description="The record's identity in this system; its first byte is the `type`.")
    # DateTime, not SQLModel's own: filters read a time they are given only for DateTime columns
    created: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'server_default': FetchedValue(), 'nullable': False}, description='When the record was made.')
    updated: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'onupdate': func.now()}, description='When the record was last changed.')
    type: Type | None = Field(None, sa_type=TypeCode, sa_column_kwargs={'server_default': FetchedValue()}, description='What the record is: the first byte of its `id`. Read only.')

    @classmethod
    def makes(cls) -> Type:
        """The type its table makes: a table makes its own type only."""
        return Type[cls.__tablename__.upper()]

    @classmethod
    async def write(cls, db: AsyncSession, id: UUID | None, sent: SQLModel) -> Self:
        """Merged into the record when the id is there, `data` and `meta` merged and a null removing a key; created when it is not, with
        that id. Stored at the commit. A field its table has not (an event's `ts` sent to a node) and an id of another type are refused."""
        if extra := sent.model_fields_set - cls.model_fields.keys():
            raise HTTPException(422, f'a {cls.__tablename__} has no {", ".join(sorted(extra))}')
        if id and (row := await db.get(cls, id)):
            change = {k: getattr(sent, k) for k in sent.model_fields_set - {'id'}}   # what was sent, a span still a Span
            for key in ('data', 'meta'):
                if key in change:
                    change[key] = {k: v for k, v in (getattr(row, key) | change[key]).items() if v is not None}
            return row.sqlmodel_update(change)
        if id and id.bytes[0] != cls.makes():   # an id's first byte is its type: a file's id would make a record in the wrong table
            raise HTTPException(422, f'{id} is of type {id.bytes[0]:#04x}, which this path does not make')
        row = cls.model_validate(sent, update={'id': id})
        db.add(row)
        return row

    @classmethod
    async def read(cls, db: AsyncSession, id: UUID) -> Self:
        """404 when there is none (`missing`)."""
        return await db.get_one(cls, id)


class Record(RecordFields, Stored, table=True):
    """A record as the store holds it. A record of any type: reading `record` returns every type's rows with these columns."""


class Node(RecordFields, Stored, table=True):
    """A node: a record with children, which links join."""


class Event(EventFields, Stored, table=True):
    """An event: a thing that happened, and when."""


class Activity(ActivityFields, Stored, table=True):
    """An activity: a named span of time."""


class Link(LinkFields, Stored, table=True):
    """A link as the store holds it."""


TABLES = {t.makes(): t for t in (Record, Node, Event, Activity, Link)}   # the types the core makes, each in its own table
READ = TABLES | {Type.FILE: Node, Type.SESSION: Activity, Type.MESSAGE: Event, Type.WORK: Activity}   # and the others, read with the columns of the basic type each is made from
AnyRecord = Record | Node | Event | Activity | Link   # a record read with the columns of its type's table


class TypeFields(SQLModel):
    """A type the store holds records of."""
    id: int = Field(primary_key=True, description="Its code: the first byte of a record's `id`.")
    name: str = Field(sa_type=String, description='Its name, as `type` is written in the spec.')
    title: str | None = Field(None, sa_type=String, description='Its name for display.')


class RecordType(TypeFields, table=True):
    """A type as the store holds it."""
    __tablename__ = 'record_types'


class TypeRead(TypeFields):
    """A type as `GET /types` gives it."""
    read_as: str = Field(description="The schema of this document its records are read with: its own, or that of the basic type it is made from.")


async def types_agree():
    """The store's types are `Type`'s, code for code and name for name; a store that differs is not this code's to serve."""
    async with AsyncSession(engine) as db:
        stored = {t.id: t.name for t in (await db.exec(select(RecordType))).all()}
    if stored != {t.value: t.name.lower() for t in Type}:
        raise RuntimeError(f'the store\'s record_types {stored} are not the types this code makes and reads')


router = APIRouter()


@router.get('/types', response_model=list[TypeRead], tags=['types'], summary='List the types')
async def types(db: Db):
    """Every type a record can be, by its code: what `type` takes in a record search, and the schema its records are read with."""
    rows = (await db.exec(select(RecordType).order_by(RecordType.id))).all()
    return [TypeRead(**t.model_dump(), read_as=READ.get(t.id, Record).__name__) for t in rows]


@router.post('/records', response_model=AnyRecord, tags=['records'], summary='Create a record')
async def record_create(db: Db, record: Fields, type: Type = Type.RECORD):
    """Of the `type` given: a record, a node, an event with its `ts` or an activity with its `span`, in its type's table.
    It comes back with the `id`, `type` and `created` the store gave it."""
    if type not in TABLES:
        raise HTTPException(422, f'the core does not make a {type.name.lower()}')
    return await saved(db, await TABLES[type].write(db, None, record))


@router.get('/records/{id}', response_model=AnyRecord, tags=['records'], summary='Read a record')
async def record_read(db: Db, id: UUID):
    """With the columns of its type's table, the `id` saying its type; a type the core does not make, with those of the basic type
    it is made from (a session's `span`, a message's `ts`). 404 when there is none."""
    return await READ.get(id.bytes[0], Record).read(db, id)


@router.put('/records/{id}', response_model=AnyRecord, tags=['records'], summary='Update a record')
async def record_update(db: Db, id: UUID, record: Fields):
    """Merged with what is sent when the `id` is there, created with that `id` when it is not. Fields not sent are left as they are.
    The `id` says its type, so its table; a type the core does not make is updated in the columns it is read with."""
    return await saved(db, await READ.get(id.bytes[0], Record).write(db, id, record))


@router.get('/records', response_model=Page[AnyRecord], tags=['records'], summary='Search records')
async def record_search(db: Db, type: Type | None = None, conditions: QueryParams = Depends(), params: Params = Depends()):
    """Of one `type`, with the columns it is read with, or of every type, with the record columns.

    `filters` is one JSON document of conditions on any column,
    `{"parent_id": {"$eq": "…"}, "status": {"$ne": "abandoned"}, "name": {"$contains": "x"}}`, with the operators
    `$eq` `$ne` `$gt` `$gte` `$lt` `$lte` `$in` `$contains` `$startswith` `$isempty` `$isnotempty`, joined by `$and` `$or`.
    A time in a condition is UTC in whole seconds, `2026-10-16T13:00:00Z` or the same without the `Z`; one with an offset is refused.
    A key inside `data` or `meta` is not a column: no condition reaches it.
    `sort` is `column:asc` or `column:desc`; `search` is text looked for in every text column.

    A page is `limit` records after `cursor`, with the `total` and `next`, the cursor of the page after it, none after the last.
    Every match when no `limit` is given."""
    model = READ.get(type, Record)
    query = build_query(model, conditions)   # querybuilder's select, over the type's table or the one it is made from
    return await paged(db, query.where(model.type == type) if type else query, model, params)


@router.get('/records/{id}/records', response_model=list[AnyRecord], tags=['records'], summary="List a record's children")
async def record_list(db: Db, id: UUID, type: Type | None = None):
    """`list`, a simple select of like records (Linked Data.md, Operations): the records whose parent it is, in the order they were
    made, of one `type` with the columns it is read with, or of every type with the record columns. No query, that is search, and
    not paged: more than `LIST` children, or more than `LIST_BYTES` of their `data` and `meta`, are refused with their count and
    size, and search pages them."""
    model = READ.get(type, Record)
    query = select(model).where(model.parent_id == id, *([model.type == type] if type else [])).order_by(model.created)
    return await listed(db, query, f'records are under {id}')


@router.get('/records/{id}/links', response_model=Page[Link], tags=['links'], summary="Search a node's links")
async def record_links(db: Db, id: UUID, query=QueryBuilder(Link), params: Params = Depends()):
    """From it and to it; `filters`, `sort`, `search` and paging as in record search."""
    return await paged(db, query.where(or_(Link.from_id == id, Link.to_id == id)), Link, params)


@router.get('/links', response_model=Page[Link], tags=['links'], summary='Search links')
async def link_search(db: Db, query=QueryBuilder(Link), params: Params = Depends()):
    """`filters` on any of a link's columns, `from_id` and `to_id` among them; `sort`, `search` and paging as in record search."""
    return await paged(db, query, Link, params)


@router.post('/links', response_model=Link, tags=['links'], summary='Create a link')
async def link_create(db: Db, record: LinkFields):
    """It needs `from_id` (its creator) and `to_id`."""
    return await saved(db, await Link.write(db, None, record))


@router.get('/links/{id}', response_model=Link, tags=['links'], summary='Read a link')
async def link_read(db: Db, id: UUID):
    """404 when there is none."""
    return await Link.read(db, id)


@router.put('/links/{id}', response_model=Link, tags=['links'], summary='Update a link')
async def link_update(db: Db, id: UUID, record: LinkFields):
    """As a record is updated: merged when the `id` is there, created when it is not."""
    return await saved(db, await Link.write(db, id, record))


@router.delete('/links/{id}', status_code=204, tags=['links'], summary='Delete a link')
async def link_delete(db: Db, id: UUID):
    """Only links are deleted; any other record is kept, and its `status` says it is abandoned."""
    await db.execute(delete(Link).where(Link.id == id))
    await db.commit()


def typed(path: str, model: type[Stored], fields: type[SQLModel], name: str) -> APIRouter:
    """A type's path: create, read, update and search on the type's own table with its own fields, written by the table's class."""
    routes = APIRouter(tags=[name])

    @routes.post(path, response_model=model, summary=f'Create a {name}')
    async def create(db: Db, record: fields):
        """It comes back with the `id`, `type` and `created` the store gave it."""
        return await saved(db, await model.write(db, None, record))

    @routes.get(path + '/{id}', response_model=model, summary=f'Read a {name}')
    async def read(db: Db, id: UUID):
        """404 when there is none."""
        return await model.read(db, id)

    @routes.put(path + '/{id}', response_model=model, summary=f'Update a {name}')
    async def update(db: Db, id: UUID, record: fields):
        """Merged with what is sent when the `id` is there, created with that `id` when it is not."""
        return await saved(db, await model.write(db, id, record))

    @routes.get(path, response_model=Page[model], summary=f'Search {name}s')
    async def search(db: Db, query=QueryBuilder(model), params: Params = Depends()):
        """`filters`, `sort`, `search` and paging as in record search; the type's own records, not those of the types made from it."""
        return await paged(db, query.with_hint(model.__table__, 'ONLY', 'postgresql'), model, params)

    return routes


async def refused(request: Request, e: StatementError):
    """What a table refuses, a link without an end, a parent of another type, a name taken under its parent, a value Postgres cannot hold,
    and a filter its column cannot take, an operator its type has not or a value not of its kind, is the caller's to fix: 422 with the
    reason. Any other failure is the API's own."""
    if isinstance(e, (IntegrityError, DataError)) or isinstance(e.orig, (UndefinedFunction, ValidationError)):
        return JSONResponse({'detail': str(e.orig).strip()}, status_code=422)
    raise e


async def missing(request: Request, e: NoResultFound):
    """A record read that is not there: 404."""
    return JSONResponse({'detail': 'Not Found'}, status_code=404)


def handled(api: FastAPI) -> FastAPI:
    """An API answering as the core does: what a table refuses 422, a record not there 404, its searches paged."""
    api.add_exception_handler(StatementError, refused)
    api.add_exception_handler(NoResultFound, missing)
    add_pagination(api)
    return api


app = FastAPI(
    title='Linked Data',
    version='1',   # the major version its path carries, /ld/v1 (Alex 10-16 09:48: versions in the URL)
    summary='Records and the links between them: create, read, update, delete, search.',
    openapi_tags=[
        {'name': 'types', 'description': 'What a record can be.'},
        {'name': 'records', 'description': 'Every record of every type.'},
        {'name': 'links', 'description': 'The links between nodes.'}],
)
app.include_router(router)
handled(app)


def api_at(path: str, name: str, summary: str, *routers: APIRouter) -> FastAPI:
    """An API built on the core, separate from it: its own paths under `path` and its own documentation there, `{path}/docs`."""
    built = FastAPI(title=f'Linked Data: {name}', version='1', summary=summary, docs_url=f'{path}/docs', openapi_url=f'{path}/openapi.json')
    for routes in routers:
        built.include_router(routes)
    return handled(built)


def served(apis: dict[str, FastAPI]):
    """Each API built on the core answers its path and the paths under it, the core every other. A mount of each at its path would
    leave its bare path to the core, since a mount takes only the paths under it, so the path picks the API."""
    async def route(scope, receive, send):
        path = scope['path'][len(scope.get('root_path', '')):]
        await next((a for p, a in apis.items() if path == p or path.startswith(p + '/')), app)(scope, receive, send)
    return route
