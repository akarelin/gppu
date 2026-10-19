"""Linked Data: records and the links between them, on Postgres, and what an API of a type is built from (_Projects/Linked Data,
"Linked Data - Universal types, statuses and sharding", # Implementation). The core's tables (`Record`, `Node`, `Collection`, `View`,
`Event`, `Message`, `Activity`, `Link`) and what the types made from content, resource and container take (`Content`, `Resource`,
`Container`), the rules a record is written by on its class (`Stored.write`, `contained`), the core's paths (`app`: `/types`,
`/records`, `/links`), and for a domain's API: `typed()`, its types' create, read, update and search; `listed()` and `paged()`, its
lists and pages; `api_at()`, the API with its own documentation; `served()`, the APIs at one address. The tables are made by the
store's `schema.sql` (RAN `Projects/ld`); `connect()` opens the store.

Needs the `ld` extra, and fastapi-querybuilder installed with `--no-deps`: its metadata lists poetry, uvicorn and aiosqlite as runtime
dependencies."""
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Annotated, Any, ClassVar, Self, TypeVar, Union
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
from pydantic import ConfigDict, GetCoreSchemaHandler, GetJsonSchemaHandler, TypeAdapter, ValidationError, field_validator, model_validator
from pydantic_core import core_schema
from sqlakeyset import custom_bookmark_type
from sqlalchemy import DateTime, FetchedValue, SmallInteger, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, Range
from sqlalchemy.exc import DataError, IntegrityError, NoResultFound, StatementError
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: F401  RAN Projects/ld's checks make their engine with ld.create_async_engine
from sqlalchemy.sql.elements import UnaryExpression
from sqlalchemy.sql.visitors import iterate
from sqlmodel import Column, Field, SQLModel, delete, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..data import async_engine
from ..gppu import TimeSpan

T = TypeVar('T')

engine = None   # the store, opened by connect()
LIST = 1000   # the most records a list sends: the older data's largest list of like records is a folder's 585 files (work 15, a location's runs 16, 2026-10-17)
LIST_BYTES = 1_000_000   # and the most data it sends, `data` and `meta` as Postgres stores them: that folder's are 187 kB (work 45 kB; a session's messages up to 145 MB, so they are read a page at a time)
DATETIME, DURATION = TypeAdapter(datetime), TypeAdapter(timedelta)
STATUSES = ('new', 'active', 'pending', 'discarded', 'rejected', 'archived')   # every record's (the spec's Record, and # States); a type adds its own


def connect(dsn: str):
    """The store at `dsn`, `postgresql+psycopg://user:password@host:port/database`, through gppu.data's `async_engine`; a filter's
    time is read without its zone, so compared as UTC."""
    global engine
    engine = async_engine(dsn)


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
    """A `list` (# Universals, Operations), not paged: every row the query selects, in its order, refused with 422 naming their count
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
    """What a record is: the first byte of its `id`. The store's `record_types` holds the same codes (`types_agree`). A link's id
    is 0xA0 to 0xAF (`LINKS`)."""
    RECORD = 0x01
    NODE = 0x02
    CONTENT = 0x05
    RESOURCE = 0x06
    CONTAINER = 0x07
    COLLECTION = 0x08
    VIEW = 0x09
    EVENT = 0x10
    ACTIVITY = 0x11
    MESSAGE = 0x12
    FS_NODE = 0x20
    FS_LOCATION = 0x21
    FS_FILE = 0x22
    FS_INDEX = 0x23
    SESSION = 0x30
    SESSION_MESSAGE = 0x31
    WORK = 0x40
    TASK = 0x41
    PROJECT = 0x42
    LINK = 0xA0


LINKS = range(0xA0, 0xB0)   # a link's ids


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
    status: str | None = Field(None, sa_type=String, description='Slug: ' + ', '.join(f'`{s}`' for s in STATUSES) + ' on any record, or one its type adds; any other is refused.')
    name: str | None = Field(None, sa_type=String, description='Name used for display.')
    data: dict = Field(default_factory=dict, sa_type=JSONB, description='What the record says about the thing. On update, merged into what is there; a null removes a key.')
    meta: dict = Field(default_factory=dict, sa_type=JSONB, description='How the record came to be: who made it, from what, when it was seen. `meta.tags`: always a list of strings. Merged on update as `data` is.')
    parent_id: UUID | None = Field(None, description='The container the record belongs to.')

    @model_validator(mode='before')
    @classmethod
    def storable(cls, v: Any) -> Any:
        return nul_free(v)

    @field_validator('meta')
    @classmethod
    def tags(cls, meta: dict) -> dict:
        if meta.get('tags') is not None and not (isinstance(meta['tags'], list) and all(isinstance(t, str) for t in meta['tags'])):
            raise ValueError('meta.tags is a list of strings')
        return meta


class LinkFields(RecordFields):
    """A link as a caller sends it: it joins one node to another, so it has a direction."""
    from_id: UUID | None = Field(None, description='The node where it starts.')
    to_id: UUID | None = Field(None, description='The node where it ends.')


def utc(t: Any) -> datetime | None:
    """A time as pydantic reads it (ISO 8601, or seconds), one without a zone UTC, as the store holds it: Postgres takes a range of
    times without a zone for a tsrange, not a span."""
    t = None if t is None else DATETIME.validate_python(t)
    return t.replace(tzinfo=UTC) if t and not t.tzinfo else t


class Span(TimeSpan):
    """gppu's `TimeSpan` as Linked Data reads and sends it, in any of its forms: `start` and `end`, an open end left out; `date` and
    `duration` (ISO 8601, or seconds); a `date` alone; a `ts` alone. A time without a zone is UTC, as the store holds it, and a span is
    sent in UTC: `{"start", "end", "bounds"}`."""
    def __init__(self, start=None, end=None, *, date=None, duration=None, ts=None, bounds: str = '[]'):
        super().__init__(utc(start), utc(end), date=utc(date), ts=utc(ts), bounds=bounds,
                         duration=None if duration is None else DURATION.validate_python(duration))

    def sent(self) -> dict:
        return {'start': self.start.astimezone(UTC), 'end': self.end and self.end.astimezone(UTC), 'bounds': self.bounds}

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        def read(v: Any) -> 'Span':   # a span, or the fields of one; what TimeSpan refuses pydantic answers 422 with
            if isinstance(v, cls):
                return v
            if not isinstance(v, dict):
                raise ValueError('a span is an object: start and end, date and duration, date, or ts')
            return cls(**v)
        return core_schema.no_info_plain_validator_function(read, serialization=core_schema.plain_serializer_function_ser_schema(cls.sent))

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler) -> dict:
        return {'title': 'Span', 'type': 'object', 'description': cls.__doc__, 'properties': {
            'start': {'type': 'string', 'format': 'date-time', 'title': 'Start'},
            'end': {'anyOf': [{'type': 'string', 'format': 'date-time'}, {'type': 'null'}], 'default': None, 'title': 'End'},
            'bounds': {'type': 'string', 'enum': ['[]', '[)'], 'default': '[]', 'title': 'Bounds'}}}


SPAN = TypeAdapter(Span)


class SpanColumn(TypeDecorator):
    """A span as Postgres holds it: a tstzrange with the span's bounds. A filter's value is a span in one of the spec's forms, or a
    time, that second; Postgres orders spans by their start, then their end."""
    impl = TSTZRANGE
    cache_ok = True

    def process_bind_param(self, span, dialect):
        if span is None:
            return None
        if not isinstance(span, Span):
            span = Span(**span) if isinstance(span, dict) else Span(ts=span)
        return Range(span.start, span.end, bounds=span.bounds)

    def process_result_value(self, value, dialect):
        return None if value is None else Span(start=value.lower, end=value.upper, bounds=value.bounds)


custom_bookmark_type(Span, 'span', deserializer=SPAN.validate_json, serializer=lambda s: SPAN.dump_json(s).decode())   # a page sorted by span carries one in its cursor


class EventFields(RecordFields):
    """An event as a caller sends it: a thing that happened, and when."""
    ts: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'nullable': False}, description='When it happened.')


class ActivityFields(RecordFields):
    """An activity as a caller sends it: a named span of time."""
    span: Span | None = Field(None, sa_type=SpanColumn, sa_column_kwargs={'nullable': False}, description='When it went on: `start` and `end`; `date` and `duration`; a `date` alone, one day; a `ts` alone, one second.')


class ViewFields(RecordFields):
    """A view as a caller sends it: a query against external data, and when it was last run."""
    query: dict | None = Field(None, sa_type=JSONB(none_as_null=True), sa_column_kwargs={'nullable': False}, description='The query against external data.')   # none is SQL's NULL, not JSON's null, so Postgres refuses a view without one
    last_refreshed: datetime | None = Field(None, sa_type=DateTime(timezone=True), description='When it was last run, so its result can be refreshed.')


class Fields(EventFields, ActivityFields, ViewFields):
    """A record as a caller sends it to `/records`: a record's fields, an event's `ts`, an activity's `span`, a view's `query` and
    `last_refreshed`; each type takes those its table has."""


class TypeCode(TypeDecorator):
    """A record's `type` as Postgres computes it from the `id` (schema.sql), read as the `Type` it names."""
    impl = SmallInteger
    cache_ok = True

    def process_result_value(self, value, dialect):
        return None if value is None else Type(value) if value in Type else value   # a link's 0xA1 to 0xAF have no name in record_types


class Stored(SQLModel):
    """The columns the store fills in, and how a record is written and read. A table is named by its class, its type by its table."""
    __mapper_args__ = {'eager_defaults': True}   # the id, type and times the table makes come back with the insert
    id: UUID | None = Field(None, primary_key=True, sa_column_kwargs={'server_default': FetchedValue()},
                            description="The record's identity in this system; its first byte is the `type`.")
    # DateTime, not SQLModel's own: filters read a time they are given only for DateTime columns
    created: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'server_default': FetchedValue(), 'nullable': False}, description='When the record was made.')
    updated: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'onupdate': func.now()}, description='When the record was last changed.')
    type: Type | int | None = Field(None, sa_type=TypeCode, sa_column_kwargs={'server_default': FetchedValue()}, description='What the record is: the first byte of its `id`. Read only.')
    STATUSES: ClassVar[tuple[str, ...]] = ()   # the statuses its type adds to every record's
    PARENTS: ClassVar[tuple[Type, ...]] = ()   # the types its parent is, where the spec names them; else any container

    @classmethod
    def makes(cls) -> Type:
        """The type its table makes: a table makes its own type only."""
        return Type[cls.__tablename__.upper()]

    @classmethod
    def takes(cls, code: int) -> bool:
        """Whether an id whose first byte is `code` is made in its table."""
        return code == cls.makes()

    @classmethod
    async def write(cls, db: AsyncSession, id: UUID | None, sent: SQLModel) -> Self:
        """Merged into the record when the id is there, `data` and `meta` merged and a null removing a key; created when it is not, with
        that id. Stored at the commit. A field its table has not (an event's `ts` sent to a node), an id of another type, and a parent
        that is not a container its type may be in are refused."""
        if extra := sent.model_fields_set - cls.model_fields.keys():
            raise HTTPException(422, f'a {cls.__tablename__} has no {", ".join(sorted(extra))}')
        if id and (row := await db.get(cls, id)):
            kind = made(row.type)   # its own type, also when written as the type it is read as: a task's through /records
            statused(sent, kind)
            change = {k: getattr(sent, k) for k in sent.model_fields_set - {'id'}}   # what was sent, a span still a Span
            for key in ('data', 'meta'):
                if key in change:
                    change[key] = {k: v for k, v in (getattr(row, key) | change[key]).items() if v is not None}
            row = row.sqlmodel_update(change)
        else:
            if id and not cls.takes(id.bytes[0]):   # an id's first byte is its type: a file's id would make a record in the wrong table
                raise HTTPException(422, f'{id} is of type {id.bytes[0]:#04x}, which this path does not make')
            kind = cls
            statused(sent, kind)
            row = cls.model_validate(sent, update={'id': id})
            db.add(row)
        if 'parent_id' in sent.model_fields_set and row.parent_id:
            await contained(db, kind, row)
        return row

    @classmethod
    async def read(cls, db: AsyncSession, id: UUID) -> Self:
        """404 when there is none (`missing`)."""
        return await db.get_one(cls, id)


def made(code: int) -> type[Stored]:
    """The class of the table a type is made in, wherever it is defined: work's and sessions' are outside gppu."""
    for table in Stored.__subclasses__():
        if hasattr(table, '__table__') and table.takes(code):
            return table
    raise RuntimeError(f'no table here makes type {code:#04x}: the module that makes it is not imported')


def statused(sent: SQLModel, table: type[Stored]):
    """A status is every record's (`STATUSES`) or one its table's type adds; any other is refused."""
    if sent.status not in (None, *STATUSES, *table.STATUSES):
        raise HTTPException(422, f"a {table.__tablename__}'s status is {', '.join(STATUSES + table.STATUSES)}, not {sent.status}")


class Content:
    """What a type made from content takes: a record that is the content itself, held in the record, where a resource only points
    to something outside."""


class Container:
    """What a type made from container takes: the records whose `parent_id` it is belong to it. A record's parent is a container."""


class Resource(Container):
    """What a type made from resource takes: a container that points to something outside Linked Data, reached rather than stored."""


async def contained(db: AsyncSession, kind: type[Stored], row: Stored):
    """A record's parent is a container (`Container`), of a type its own type may be in where the spec names one (`PARENTS`), and
    neither the record itself nor a record it holds: containers nest."""
    if not (parent := await db.get(Record, row.parent_id)):   # every table inherits record: a record of any type
        raise HTTPException(422, f'no record {row.parent_id} to hold it')
    table = made(parent.type)
    if kind.PARENTS and parent.type not in kind.PARENTS:
        raise HTTPException(422, f"a {kind.__tablename__}'s parent is a {' or a '.join(t.name.lower() for t in kind.PARENTS)}, not a {table.__tablename__}")
    if not issubclass(table, Container):
        raise HTTPException(422, f'{parent.id} is a {table.__tablename__}, not a container')
    seen, at = set(), parent
    while at and at.id not in seen:   # up the containers it would be in
        if at.id == row.id:
            raise HTTPException(422, f'{row.id} would be in itself')
        seen.add(at.id)
        at = at.parent_id and await db.get(Record, at.parent_id)


class Record(RecordFields, Stored, table=True):
    """Everything stored is a record, and every type is built on it: reading `record` returns every type's rows with these columns."""


class Node(RecordFields, Stored, table=True):
    """A record that links join and that can hold other records: every type but record and link."""


class Collection(RecordFields, Stored, table=True):
    """A node that groups the nodes linked to it; one node can be in many collections."""


class View(ViewFields, Container, Stored, table=True):
    """A container that holds a query against external data and when it was last run, so its result can be refreshed."""


class Event(EventFields, Stored, table=True):
    """Something that happened at one moment, `ts`."""


class Message(EventFields, Content, Stored, table=True):
    """An event that is also content: content with the one moment it happened, `ts`."""


class Activity(ActivityFields, Stored, table=True):
    """A named timespan."""


class Link(LinkFields, Stored, table=True):
    """A record that joins one node to another, so it has a direction; its id is 0xA0 to 0xAF (`LINKS`)."""

    @classmethod
    def takes(cls, code: int) -> bool:
        return code in LINKS

    @classmethod
    async def write(cls, db: AsyncSession, id: UUID | None, sent: SQLModel) -> Self:
        """As a record is written; an end it is sent that is not a node is refused."""
        row = await super().write(db, id, sent)
        for end in (getattr(row, k) for k in ('from_id', 'to_id') if k in sent.model_fields_set):
            if end and not await db.get(Node, end):   # node's table inherits every type but record and link
                raise HTTPException(422, f'{end} is not a node')
        return row


TABLES = {t.makes(): t for t in (Record, Node, Collection, View, Event, Message, Activity, Link)}   # the types the core makes, each in its own table
READ = TABLES | {Type.CONTENT: Node, Type.RESOURCE: Node, Type.CONTAINER: Node, Type.FS_NODE: Node, Type.FS_LOCATION: Node, Type.FS_FILE: Node,
                 Type.FS_INDEX: Node, Type.SESSION: Activity, Type.SESSION_MESSAGE: Message, Type.WORK: Activity, Type.TASK: Activity,
                 Type.PROJECT: Activity} | dict.fromkeys(LINKS, Link)   # and the others, read with the columns of the type each is made from
AnyRecord = Record | Node | Collection | View | Event | Message | Activity | Link   # a record read with the columns of its type's table


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
    read_as: str = Field(description="The schema of this document its records are read with: its own, or that of the type it is made from.")


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
    """Of the `type` given, in its type's table: a record, a node, a collection, a view with its `query`, an event or a message with
    its `ts`, an activity with its `span`. It comes back with the `id`, `type` and `created` the store gave it."""
    if type not in TABLES:
        raise HTTPException(422, f'the core does not make a {type.name.lower()}')
    return await saved(db, await TABLES[type].write(db, None, record))


@router.get('/records/{id}', response_model=AnyRecord, tags=['records'], summary='Read a record')
async def record_read(db: Db, id: UUID):
    """With the columns of its type's table, the `id` saying its type; a domain's type, with those of the type it is made from (a
    session's `span`, a session message's `ts`). 404 when there is none."""
    return await READ.get(id.bytes[0], Record).read(db, id)


@router.put('/records/{id}', response_model=AnyRecord, tags=['records'], summary='Update a record')
async def record_update(db: Db, id: UUID, record: Fields):
    """Merged with what is sent when the `id` is there, created with that `id` when it is not. Fields not sent are left as they are.
    The `id` says its type, so its table; a domain's type is updated in the columns it is read with."""
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
    """`list`, a simple select of like records (# Universals, Operations): the records whose parent it is, in the order they were
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
    """Only links are deleted; any other record is kept, its `status` saying what became of it."""
    await db.execute(delete(Link).where(Link.id == id))
    await db.commit()


def typed(path: str, fields: type[SQLModel], name: str, *models: type[Stored]) -> APIRouter:
    """A domain's path for its types: create, read, update and search, each type in its own table, with the fields a caller sends,
    written by its table's class. A path of several types takes the `type` a create makes, the first by default, and the one a
    search reads, every one of them by default; a read or an update's `id` says its type."""
    routes, base, tables = APIRouter(tags=[name]), models[0], {m.makes(): m for m in models}
    One = Union[models]   # a record of the path, read with its own type's columns

    def named(type: Type | None = None):
        """The table of the `type` named, one of the path's."""
        if type is not None and type not in tables:
            raise HTTPException(422, f'{path} has {", ".join(t.name.lower() for t in tables)}, not {type.name.lower()}')
        return type and tables[type]
    kind = named if len(models) > 1 else lambda: base

    @routes.post(path, response_model=One, summary=f'Create a {name}')
    async def create(db: Db, record: fields, model=Depends(kind)):
        """It comes back with the `id`, `type` and `created` the store gave it."""
        return await saved(db, await (model or base).write(db, None, record))

    @routes.get(path + '/{id}', response_model=One, summary=f'Read a {name}')
    async def read(db: Db, id: UUID):
        """404 when there is none."""
        return await tables.get(id.bytes[0], base).read(db, id)

    @routes.put(path + '/{id}', response_model=One, summary=f'Update a {name}')
    async def update(db: Db, id: UUID, record: fields):
        """Merged with what is sent when the `id` is there, created with that `id` when it is not."""
        return await saved(db, await tables.get(id.bytes[0], base).write(db, id, record))

    @routes.get(path, response_model=Page[One], summary=f'Search {name}s')
    async def search(db: Db, conditions: QueryParams = Depends(), params: Params = Depends(), model=Depends(kind)):
        """`filters`, `sort`, `search` and paging as in record search: of a type, its own table's records, not those of the types made
        from it; of every type of the path, with the columns of the first."""
        query = build_query(model or base, conditions)
        return await paged(db, query.with_hint(model.__table__, 'ONLY', 'postgresql') if model else query, model or base, params)

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
