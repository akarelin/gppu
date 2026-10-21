"""Linked Data: records and the links between them, on Postgres, and what an API of a type is built from (_Projects/Linked Data,
"Linked Data - Universal types, statuses and sharding", # Implementation). `_Record`, every record's columns and its operations
(# Universals, Operations: create, read, update, delete, list, search), with no table; the types that add columns as data models on
it (`_Event`, `_Activity`, `_View`, `_Link`); and each type's class, which only defines its table: the core's (`Record`, `Node`,
`Collection`, `View`, `Event`, `Message`, `Activity`, `Link`) here, a domain's in its own module. `typed()` gives a path its types'
create, read, update, delete and search, the core's `/records` and `/links` and each domain's; `app` is the core with `/types` and
what controls read; `api_at()`, a domain's API with its own documentation; `served()`, the APIs at one address, on the store of the
app that serves them. The tables are made by the store's `schema.sql` (RAN `Projects/ld`), and how they inherit is Postgres'. The
store is the app's: a `gppu.data._SQABase`, which RAN `Projects/ld/api.py`'s `LDAPI` is, gives the engine and each request's
database session.

Needs the `ld` extra, and fastapi-querybuilder installed with `--no-deps`: its metadata lists poetry, uvicorn and aiosqlite as runtime
dependencies."""
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from collections.abc import Sequence
from typing import Any, ClassVar, Self, TypeVar, Union
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_pagination import add_pagination, create_page
from fastapi_pagination.cursor import CursorPage   # a page carries the cursor of the next one (sqlakeyset reads after the last row)
from fastapi_pagination.customization import (CustomizedPage, UseExcludedFields, UseFieldsAliases, UseIncludeTotal, UseName,
                                              UseOptionalParams, UseParamsFields)
from fastapi_pagination.ext.sqlalchemy import apaginate   # querybuilder builds SQLAlchemy selects
from fastapi_querybuilder import QueryParams, build_query
from psycopg.errors import UndefinedFunction
from pydantic import ConfigDict, GetCoreSchemaHandler, GetJsonSchemaHandler, TypeAdapter, ValidationError, field_validator
from pydantic_core import core_schema
from sqlakeyset import custom_bookmark_type
from sqlalchemy import DateTime, FetchedValue, SmallInteger, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, Range
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.sql.elements import UnaryExpression
from sqlalchemy.sql.visitors import iterate
from sqlmodel import Column, Field, SQLModel, delete, func, or_, select

from ..data import _SQABase
from ..gppu import TimeSpan

T = TypeVar('T')

LIST = 1000   # the most records a list sends: the older data's largest list of like records is a folder's 585 files (work 15, a location's runs 16, 2026-10-17)
LIST_BYTES = 1_000_000   # and the most data it sends, `data` and `meta` as Postgres stores them: that folder's are 187 kB (work 45 kB; a session's messages up to 145 MB, so they are read a page at a time)
DATETIME, DURATION = TypeAdapter(datetime), TypeAdapter(timedelta)
STORE = ('id', 'created', 'updated', 'type')   # the columns Postgres fills: a caller does not send them


async def transaction():
    """Each request is one transaction, a FastAPI dependency with yield of the API `served()` serves: the request's database
    session, the store's scoped session for the task serving it, committed when the call ends, rolled back on an error and
    removed. The store's zone is UTC, so a filter's time without a zone is compared as UTC."""
    try:
        yield
        await _Record.db().commit()
    except Exception:
        await _Record.db().rollback()
        raise
    finally:
        await _Record.db.remove()

Page = CustomizedPage[CursorPage[T], UseName('Page'), UseIncludeTotal(True), UseOptionalParams(),
                      UseParamsFields(size=Query(None, ge=1, alias='limit', description='How many records a page holds.')),
                      UseExcludedFields('current_page', 'current_page_backwards'),
                      UseFieldsAliases(next_page='next', previous_page='previous')]   # `limit` records after `cursor`, the total, and `next`
Params = Page.__params_type__
LEAST = {str: '', int: 0, UUID: UUID(int=0), datetime: datetime.min.replace(tzinfo=ZoneInfo('UTC'))}   # what an empty column is sorted as


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


# ++     _Record: every record's columns and its operations; a type's class only defines its table

class _Record(SQLModel):
    """Everything stored is a record (# Record), and every type is built on it: its columns and its operations (# Universals,
    Operations), with no table of its own. A type's class is made from it, or from a data model on it, and only defines its table,
    `class Node(_Record, table=True)`, so it is created, read, updated, deleted, listed and searched in its own table by its own
    rules. What a caller sends is a record without the columns Postgres fills (`STORE`); a field its type has not is refused."""
    model_config = ConfigDict(extra='forbid')
    db: ClassVar[Any] = None   # the store's scoped session, set once by served(): called, the session of the request being served
    __mapper_args__ = {'eager_defaults': True}   # the id, type and times the table makes come back with the insert
    id: UUID | None = Field(None, primary_key=True, sa_column_kwargs={'server_default': FetchedValue()},
                            description="The record's identity in this system; its first byte is the `type`.")
    # DateTime, not SQLModel's own: filters read a time they are given only for DateTime columns
    created: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'server_default': FetchedValue(), 'nullable': False}, description='When the record was made.')
    updated: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'onupdate': func.now()}, description='When the record was last changed.')
    type: int | None = Field(None, sa_type=SmallInteger, sa_column_kwargs={'server_default': FetchedValue()}, description='What the record is: the first byte of its `id`. Read only.')
    # String, not SQLModel's own AutoString: search looks for its text only in String columns
    subtype: str | None = Field(None, sa_type=String, description='Plain text refining the `type`, from a short list per type that Postgres does not enforce.')
    status: str | None = Field(None, sa_type=String, description='Slug, one of the statuses the spec gives its type (# States); stored as it is sent.')
    name: str | None = Field(None, sa_type=String, description='Name used for display.')
    data: dict = Field(default_factory=dict, sa_type=JSONB, description='What the record says about the thing. On update, merged into what is there; a null removes a key.')
    meta: dict = Field(default_factory=dict, sa_type=JSONB, description='How the record came to be: who made it, from what, when it was seen. `meta.tags`: always a list of strings. Merged on update as `data` is.')
    parent_id: UUID | None = Field(None, description='The container the record belongs to.')

    @field_validator('meta')
    @classmethod
    def tags(cls, meta: dict) -> dict:
        if meta.get('tags') is not None and not (isinstance(meta['tags'], list) and all(isinstance(t, str) for t in meta['tags'])):
            raise ValueError('meta.tags is a list of strings')
        return meta

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler) -> dict:
        """What a caller sends is a record without the columns Postgres fills; what the API answers has them."""
        json_schema = handler(schema)
        if handler.mode == 'validation':
            for key in STORE:
                handler.resolve_ref_schema(json_schema).get('properties', {}).pop(key, None)
        return json_schema

    @classmethod
    async def create(cls, sent: '_Record') -> Self:
        """A new record of its type from what is sent, with the id the store makes. Stored at the commit."""
        return await cls.update(None, sent)

    @classmethod
    async def read(cls, id: UUID) -> Self:
        """404 when there is none."""
        if not (row := await cls.db().get(cls, id)):
            raise HTTPException(404, f'no {cls.__tablename__} {id}')
        return row

    @classmethod
    async def update(cls, id: UUID | None, sent: '_Record') -> Self:
        """Merged into the record of that id when it is there, `data` and `meta` merged and a null removing a key; created with that id
        when it is not: an insert is an upsert. Written at once, so what Postgres fills comes back, and stored at the commit. Written by its class's rules: a task's own at its own path, a
        record's through `/records`. The columns Postgres fills and a field its table has not (an event's `ts` sent to a node) are
        refused; Postgres refuses an id of another type."""
        if filled := sent.model_fields_set & set(STORE):
            raise HTTPException(422, f'{", ".join(sorted(filled))}: the store fills them')
        if extra := sent.model_fields_set - cls.model_fields.keys():
            raise HTTPException(422, f'a {cls.__tablename__} has no {", ".join(sorted(extra))}')
        if id and (row := await cls.db().get(cls, id)):
            change = {k: getattr(sent, k) for k in sent.model_fields_set}   # what was sent, a span still a Span
            for key in ('data', 'meta'):
                if key in change:
                    change[key] = {k: v for k, v in (getattr(row, key) | change[key]).items() if v is not None}
            row = row.sqlmodel_update(change)
        else:
            row = cls.model_validate(sent, update={'id': id})
            cls.db().add(row)
        await cls.db().flush()
        return row

    @classmethod
    async def delete(cls, id: UUID) -> None:
        """With the links from it and to it; refused while it holds records, which are deleted or moved out first. 404 when there is
        none. Gone at the commit."""
        await cls.read(id)
        if n := (await cls.db().exec(select(func.count()).select_from(Record).where(Record.parent_id == id))).one():
            raise HTTPException(422, f'{id} holds {n} records: delete them or move them out first')
        await cls.db().execute(delete(Link).where(or_(Link.from_id == id, Link.to_id == id)))
        await cls.db().execute(delete(cls).where(cls.id == id))

    @classmethod
    async def list(cls, *where, order: tuple, what: str) -> Sequence[Self]:
        """A `list` (# Universals, Operations), not paged: every record of its table `where` selects, in `order`; refused with 422
        naming their count and size, `what` they are, when they are more than a list sends, `LIST` rows or `LIST_BYTES` of their
        `data` and `meta` as stored."""
        query = select(cls).where(*where)
        found = query.subquery()
        n, size = (await cls.db().exec(select(func.count(), func.coalesce(func.sum(func.pg_column_size(found.c.data) + func.pg_column_size(found.c.meta)), 0)))).one()
        if n > LIST or size > LIST_BYTES:
            raise HTTPException(422, f'{n} {what}, {size} bytes of data, more than a list sends ({LIST}, {LIST_BYTES} bytes): search them, a page at a time')
        return (await cls.db().exec(query.order_by(*order))).all()

    @classmethod
    async def search(cls, params, *where, conditions: QueryParams | None = None, only: bool = False):
        """A page of a search (# Universals, Operations): the records of its table fastapi-querybuilder's query of `conditions` and
        `where` select, `limit` of them after the last one of the page before (sqlakeyset), so the order ends with the id, which no two
        rows share; every match when no limit is given. `only` keeps to its own table's records, not those of the types made from it."""
        query = (build_query(cls, conditions) if conditions else select(cls)).where(*where)
        if only:
            query = query.with_hint(cls.__table__, 'ONLY', 'postgresql')

        def after(key):
            """A sort key a page can read after: one over a column a record may leave empty sorts that record as the column's least value."""
            column = next(c for c in iterate(key.element) if isinstance(c, Column))   # under querybuilder's lower() of a text column
            return UnaryExpression(func.coalesce(key.element, LEAST[column.type.python_type]), modifier=key.modifier) if column.nullable else key
        keys = [after(k) for k in query._order_by_clauses]   # querybuilder's sort, read as sqlakeyset reads it
        query = query.order_by(None).order_by(*keys, cls.id)
        if params.size is None:
            rows = (await cls.db().scalars(query)).all()   # querybuilder's select is SQLAlchemy's: rows of one record each
            return create_page(rows, params=params, total=len(rows))
        return await apaginate(cls.db(), query, params=params)


# ++     The data models: what a type adds to a record, and the abstract types

class _Link(_Record):
    """A link's columns: it joins one node to another, so it has a direction. Its ids are 0xA0 to 0xAF (`LINKS`)."""
    from_id: UUID | None = Field(None, description='The node where it starts.')
    to_id: UUID | None = Field(None, description='The node where it ends.')

    @classmethod
    async def update(cls, id: UUID | None, sent: _Record) -> Self:
        """As a record is written; an end it is sent that is not a node is refused."""
        row = await super().update(id, sent)
        for end in (getattr(row, k) for k in ('from_id', 'to_id') if k in sent.model_fields_set):
            if end and not await cls.db().get(Node, end):   # node's table inherits every type but record and link
                raise HTTPException(422, f'{end} is not a node')
        return row

    @classmethod
    async def delete(cls, id: UUID) -> None:
        """The link alone; the nodes at its ends stay, and a link that is not there is gone already. Gone at the commit."""
        await cls.db().execute(delete(cls).where(cls.id == id))


class _Event(_Record):
    """An event's column: when the thing happened."""
    ts: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'nullable': False}, description='When it happened.')


class _Activity(_Record):
    """An activity's column: a named span of time."""
    span: Span | None = Field(None, sa_type=SpanColumn, sa_column_kwargs={'nullable': False}, description='When it went on: `start` and `end`; `date` and `duration`; a `date` alone, one day; a `ts` alone, one second.')


class _View(_Record):
    """A view's columns: a query against external data, and when it was last run."""
    query: dict | None = Field(None, sa_type=JSONB(none_as_null=True), sa_column_kwargs={'nullable': False}, description='The query against external data.')   # none is SQL's NULL, not JSON's null, so Postgres refuses a view without one
    last_refreshed: datetime | None = Field(None, sa_type=DateTime(timezone=True), description='When it was last run, so its result can be refreshed.')


class Fields(_Event, _Activity, _View):
    """A record as a caller sends it to `/records`, of any type the core makes: a record's columns, an event's `ts`, an activity's
    `span`, a view's `query` and `last_refreshed`; each type takes those its table has."""


# ++     The core's types: each its table

class Record(_Record, table=True):
    """Everything stored is a record, and every type is built on it: reading `record` returns every type's rows with these columns."""


class Node(_Record, table=True):
    """A record that links join and that can hold other records: every type but record and link."""


class Collection(_Record, table=True):
    """A node that groups the nodes linked to it; one node can be in many collections."""


class View(_View, table=True):
    """A container that holds a query against external data and when it was last run, so its result can be refreshed."""


class Event(_Event, table=True):
    """Something that happened at one moment, `ts`."""


class Message(_Event, table=True):
    """An event that is also content: content with the one moment it happened, `ts`."""


class Activity(_Activity, table=True):
    """A named timespan."""


class Link(_Link, table=True):
    """A record that joins one node to another, so it has a direction; its id is 0xA0 to 0xAF (`LINKS`)."""


class RecordType(SQLModel, table=True):
    """A type the store holds records of."""
    __tablename__ = 'record_types'
    id: int = Field(primary_key=True, description="Its code: the first byte of a record's `id`.")
    name: str = Field(sa_type=String, description='Its name, as `type` is written in the spec.')
    title: str | None = Field(None, sa_type=String, description='Its name for display.')


async def types_agree(store: _SQABase):
    """The store's types are `Type`'s, code for code and name for name; a store that differs is not this code's to serve."""
    async with store.session() as db:
        stored = {t.id: t.name for t in (await db.exec(select(RecordType))).all()}
    if stored != {t.value: t.name.lower() for t in Type}:
        raise RuntimeError(f'the store\'s record_types {stored} are not the types this code makes and reads')


def typed(path: str, body: type[_Record], name: str, *models: type[_Record]) -> APIRouter:
    """A path for its types: create, read, update, delete and search, each type in its own table, `body` what a caller sends.
    A path of several types takes the `type` a create makes, the first by default, and the one a search reads, every one of them by
    default; a read, an update or a delete's `id` says its type, and one of a type the path has not is read and changed through
    the first, with its columns."""
    routes, base = APIRouter(tags=[name]), models[0]
    own = {Type[m.__tablename__.upper()]: m for m in models}   # the path's types, in its order
    One = Union[models]   # a record of the path, read with its own type's columns

    def made(type: Type | None = None):
        """The table of the `type` a create makes, one of the path's."""
        if type is not None and type not in own:
            raise HTTPException(422, f'{path} makes {", ".join(t.name.lower() for t in own)}, not {type.name.lower()}')
        return own[type] if type is not None else base

    @routes.post(path, response_model=One, summary=f'Create a {name}')
    async def create(record: body, model=Depends(made if len(models) > 1 else lambda: base)):
        """It comes back with the `id`, `type` and `created` the store gave it."""
        return await model.create(record)

    @routes.get(path + '/{id}', response_model=One, summary=f'Read a {name}')
    async def read(id: UUID):
        """404 when there is none."""
        return await own.get(id.bytes[0], base).read(id)

    @routes.put(path + '/{id}', response_model=One, summary=f'Update a {name}')
    async def update(id: UUID, record: body):
        """Merged with what is sent when the `id` is there, created with that `id` when it is not."""
        return await own.get(id.bytes[0], base).update(id, record)

    @routes.delete(path + '/{id}', status_code=204, summary=f'Delete a {name}')
    async def delete(id: UUID):
        """With its links; refused while it holds records, which are deleted or moved out first. 404 when there is none."""
        await own.get(id.bytes[0], base).delete(id)

    @routes.get(path, response_model=Page[One], summary=f'Search {name}s')
    async def search(type: Type | None = None, conditions: QueryParams = Depends(), params: Params = Depends()):
        """Of one `type`, or of every type of the path with the columns of the first; a type of the path, its own table's records,
        not those of the types made from it, and any other through the first, with its columns.

        `filters` is one JSON document of conditions on any column,
        `{"parent_id": {"$eq": "…"}, "status": {"$ne": "discarded"}, "name": {"$contains": "x"}}`, with the operators
        `$eq` `$ne` `$gt` `$gte` `$lt` `$lte` `$in` `$contains` `$startswith` `$isempty` `$isnotempty`, joined by `$and` `$or`.
        A time in a condition is UTC in whole seconds, `2026-10-16T13:00:00Z` or the same without the `Z`; one with an offset is refused.
        `sort` is `column:asc` or `column:desc`; `search` is text looked for in every text column.

        A page is `limit` records after `cursor`, with the `total` and `next`, the cursor of the page after it, none after the last.
        Every match when no `limit` is given."""
        if type in own:
            return await own[type].search(params, conditions=conditions, only=True)
        return await base.search(params, *([base.type == type] if type else []), conditions=conditions)

    return routes


router = APIRouter()


@router.get('/types', response_model=list[RecordType], tags=['type'], summary='List the types')
async def types():
    """Every type a record can be, by its code: what `type` takes in a record search."""
    return (await _Record.db().exec(select(RecordType).order_by(RecordType.id))).all()


@router.get('/records/{id}/records', response_model=list[Record], tags=['record'], summary="List a record's children")
async def record_list(id: UUID, type: Type | None = None):
    """`list`, a simple select of like records (# Universals, Operations): the records whose parent it is, of one `type` or of
    every type, in the order they were made. No query, that is search, and not paged: more than `LIST` children, or more than
    `LIST_BYTES` of their `data` and `meta`, are refused with their count and size, and search pages them."""
    return await Record.list(Record.parent_id == id, *([Record.type == type] if type else []), order=(Record.created,), what=f'records are under {id}')


@router.get('/records/{id}/links', response_model=Page[Link], tags=['link'], summary="Search a node's links")
async def record_links(id: UUID, conditions: QueryParams = Depends(), params: Params = Depends()):
    """From it and to it; `filters`, `sort`, `search` and paging as in record search."""
    return await Link.search(params, or_(Link.from_id == id, Link.to_id == id), conditions=conditions)


router.include_router(typed('/records', Fields, 'record', Record, Node, Collection, View, Event, Message, Activity, Link))
router.include_router(typed('/links', _Link, 'link', Link))


async def refused(request: Request, e: StatementError):
    """What a table refuses, a link without an end, a parent of another type, a name taken under its parent, a value Postgres cannot hold,
    and a filter its column cannot take, an operator its type has not or a value not of its kind, is the caller's to fix: 422 with the
    reason. Any other failure is the API's own."""
    if isinstance(e, (IntegrityError, DataError)) or isinstance(e.orig, (UndefinedFunction, ValidationError)):
        return JSONResponse({'detail': str(e.orig).strip()}, status_code=422)
    raise e


app = FastAPI(
    title='Linked Data',
    version='1',   # the major version its path carries, /ld/v1 (Alex 10-16 09:48: versions in the URL)
    summary='Records and the links between them: create, read, update, delete, search.',
    openapi_tags=[
        {'name': 'type', 'description': 'What a record can be.'},
        {'name': 'record', 'description': 'Every record of every type.'},
        {'name': 'link', 'description': 'The links between nodes.'}],
)
app.include_router(router)


def api_at(path: str, name: str, summary: str, *routers: APIRouter) -> FastAPI:
    """An API built on the core, separate from it: its own paths under `path` and its own documentation there, `{path}/docs`."""
    built = FastAPI(title=f'Linked Data: {name}', version='1', summary=summary, docs_url=f'{path}/docs', openapi_url=f'{path}/openapi.json')
    for routes in routers:
        built.include_router(routes)
    return built


def served(apis: dict[str, FastAPI], store: _SQABase) -> FastAPI:
    """The core and the APIs built on it as one API on `store`, the app's: its scoped session is every record's (`_Record.db`), set
    once here, and each request is one transaction (`transaction`). Every route in one OpenAPI document, `/openapi.json`, shown at `/docs`, each API's routes under its tag; each API built on it keeps its own
    document at `{path}/docs` as well. With no APIs, the core alone."""
    tags = {t: a.summary for a in apis.values() for ops in a.openapi()['paths'].values() for op in ops.values() for t in op.get('tags', ())}   # each API's tags, described by its summary
    one = FastAPI(title=app.title, version=app.version, summary='Records and the links between them, and the APIs built on them: '
                  + ', '.join(p.strip('/') for p in apis) + '.',
                  openapi_tags=app.openapi_tags + [{'name': t, 'description': s} for t, s in tags.items()],
                  dependencies=[Depends(transaction)], exception_handlers={StatementError: refused})
    one.include_router(router)
    for api in apis.values():
        one.include_router(api.router)
    _Record.db = store.scoped_session
    add_pagination(one)
    return one
