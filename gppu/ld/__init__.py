"""Linked Data: records and the links between them, on Postgres (_Standards/Linked Data/Linked Data.md), schema `ld`, and what
another schema's API is built from. `_Record`, every record's columns and its operations (create, read, update, delete, list,
search), with no table; `_Type` and `_Link`, the columns a type and a link add; and each table's class, which only defines its table
and the shard its ids start with (`__shard__`), shard1 its schema and shard2 the table (# UUID): `ld.records`, `ld.types` 0x0000,
`ld.nodes` 0x0001, `ld.links` 0x0010, `ld.events` 0x0020.
A record's `flags` say what can change it and whether it is in sight (`Flags`). `operations()` gives a path its tables' create, read,
update, delete and search; `app` is the core, `/records`, `/types` and `/links`; `api_at()`, another schema's API with its own
documentation; `serve()`, the APIs at one address, on the store of the app that serves them. The tables are made by the standard's
SQL, and how they inherit is Postgres'. The store is the app's: a `gppu.data._SQABase` gives the engine and each request's database
session.

Needs the `ld` extra, and fastapi-querybuilder installed with `--no-deps`: its metadata lists poetry, uvicorn and aiosqlite as runtime
dependencies."""
from datetime import UTC, datetime, timedelta
from enum import IntFlag
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
from pydantic import ConfigDict, GetCoreSchemaHandler, GetJsonSchemaHandler, TypeAdapter, ValidationError
from pydantic_core import core_schema
from sqlakeyset import custom_bookmark_type
from sqlalchemy import Computed, DateTime, FetchedValue, SmallInteger, String, TypeDecorator, UniqueConstraint, literal
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, Range
from sqlalchemy.exc import DataError, IntegrityError, StatementError
from sqlalchemy.sql.elements import UnaryExpression
from sqlalchemy.sql.sqltypes import NullType
from sqlalchemy.sql.visitors import iterate
from sqlmodel import Column, Field, SQLModel, func, or_, select

from ..data import _SQABase
from ..gppu import TimeSpan

T = TypeVar('T')

LIST = 1000   # the most records a list sends: the older data's largest list of like records is a folder's 585 files (work 15, a location's runs 16, 2026-10-17)
LIST_BYTES = 1_000_000   # and the most data it sends, `data` and `meta` as Postgres stores them: that folder's are 187 kB (work 45 kB; a session's messages up to 145 MB, so they are read a page at a time)
DATETIME, DURATION = TypeAdapter(datetime), TypeAdapter(timedelta)
STORE = ('id', 'ts', 'created', 'updated')   # the columns Postgres fills: a caller does not send them


async def transaction():
    """Each request is one transaction, a FastAPI dependency with yield of the API `serve()` serves: the request's database
    session, the store's scoped session for the task serving it, committed when the call ends and before its answer is sent
    (scope='function'; FastAPI's default runs it after, so a caller's next read could miss what it wrote), rolled back on an
    error and removed. The store's zone is UTC, so a filter's time without a zone is compared as UTC."""
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


class Flags(IntFlag):
    """A record's `flags` (# Flags): `ro` and `system` are read only, `deleted` and `archived` read only and out of sight,
    `system` and `hidden` out of sight. A record out of sight is read by its id, and no list or search returns it."""
    RO = 0x01
    SYSTEM = 0x02
    DELETED = 0x04
    HIDDEN = 0x08
    ARCHIVED = 0x10


READ_ONLY = Flags.RO | Flags.SYSTEM | Flags.DELETED | Flags.ARCHIVED
UNSEEN = Flags.SYSTEM | Flags.DELETED | Flags.HIDDEN | Flags.ARCHIVED


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

    @property
    def python_type(self):
        return Span

    def process_bind_param(self, span, dialect):
        if span is None:
            return None
        if not isinstance(span, Span):
            span = Span(**span) if isinstance(span, dict) else Span(ts=span)
        return Range(span.start, span.end, bounds=span.bounds)

    def process_result_value(self, value, dialect):
        return None if value is None else Span(start=value.lower, end=value.upper, bounds=value.bounds)


custom_bookmark_type(Span, 'span', deserializer=SPAN.validate_json, serializer=lambda s: SPAN.dump_json(s).decode())   # a page sorted by span carries one in its cursor
LEAST = {str: '', int: 0, UUID: UUID(int=0), datetime: datetime.min.replace(tzinfo=ZoneInfo('UTC'))}   # what an empty column is sorted as
LEAST[Span] = Span(*[LEAST[datetime] + timedelta(days=1)] * 2)   # a span at the least time it holds in any zone: TimeSpan reads its times in gppu's


# ++     _Record: every record's columns and its operations; a table's class only defines its table

class _Record(SQLModel):
    """Everything stored is a record (# Record), and every type is built on it: its columns and its operations, with no table of
    its own. A table's class is made from it and only defines its table, its schema and the two bytes its ids start with,
    `class Node(_Record, table=True)`, so it is created, read, updated, deleted, listed and searched in its own table by its own
    rules. What a caller sends is a record without the columns Postgres fills (`STORE`); a field its table has not is refused."""
    model_config = ConfigDict(extra='forbid')
    db: ClassVar[Any] = None   # the store's scoped session, set once by serve(): called, the session of the request being served
    __shard__: ClassVar[int]   # the first two bytes of every id in its table, shard1 its schema and shard2 the table (# UUID)
    __mapper_args__ = {'eager_defaults': True}   # the id, name, ts and times the table makes come back with the insert
    id: UUID | None = Field(None, primary_key=True, sa_column_kwargs={'server_default': FetchedValue()},
                            description="The record's identity; its first byte is shard1, its schema, and its second shard2, its table.")
    flags: int = Field(0, sa_type=SmallInteger, description='ro 1, system 2, deleted 4, hidden 8, archived 16.')
    # String, not SQLModel's own AutoString: search looks for its text only in String columns
    type: str | None = Field(None, sa_type=String, description='Slug of its type.')
    status: str | None = Field(None, sa_type=String, description="Slug of its status, one of its type's or its type's parent's.")
    name: str | None = Field(None, sa_type=String, sa_column_kwargs={'server_default': FetchedValue(), 'server_onupdate': FetchedValue()},
                             description='`data.name` when it has one, else `{type}-{id}`, unless one is sent.')
    parent_id: UUID | None = Field(None, description='The record it belongs to.')
    span: Span | None = Field(None, sa_type=SpanColumn, description='Its timespan: `start` and `end`; `date` and `duration`; a `date` alone, one day; a `ts` alone, one second.')
    # DateTime, not SQLModel's own: filters read a time they are given only for DateTime columns
    ts: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_args=[Computed('lower(span)', persisted=False)],
                                description='The start of `span`. Read only.')
    data: dict = Field(default_factory=dict, sa_type=JSONB, description='What the record says about the thing. On update, merged into what is there; a null removes a key.')
    meta: dict = Field(default_factory=dict, sa_type=JSONB, description='How the record came to be: who made it, from what, when it was seen. Merged on update as `data` is.')
    created: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'server_default': FetchedValue(), 'nullable': False}, description='When the record was made.')
    updated: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'server_onupdate': FetchedValue()}, description='When the record was last changed.')

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
        """A new record in its table from what is sent, with the id the store makes. Stored at the commit."""
        return await cls.update(None, sent)

    @classmethod
    async def read(cls, id: UUID) -> Self:
        """In sight or not; 404 when there is none."""
        if not (row := await cls.db().get(cls, id)):
            raise HTTPException(404, f'no {cls.__tablename__} {id}')
        return row

    @classmethod
    async def update(cls, id: UUID | None, sent: '_Record') -> Self:
        """Merged into the record of that id when it is there, `data` and `meta` merged and a null removing a key; created with that id
        when it is not: an insert is an upsert. A read-only record (# Flags) changes only its `flags`. Written at once, so what
        Postgres fills comes back, and stored at the commit. The columns Postgres fills and a field its table has not are refused;
        Postgres refuses an id of another table."""
        if filled := sent.model_fields_set & set(STORE):
            raise HTTPException(422, f'{", ".join(sorted(filled))}: the store fills them')
        if extra := sent.model_fields_set - cls.model_fields.keys():
            raise HTTPException(422, f'a record in {cls.__tablename__} has no {", ".join(sorted(extra))}')
        if id and (row := await cls.db().get(cls, id)):
            change = {k: getattr(sent, k) for k in sent.model_fields_set}   # what was sent, a span still a Span
            if row.flags & READ_ONLY and change.keys() - {'flags'}:
                raise HTTPException(422, f'{id} is read only ({Flags(row.flags & READ_ONLY)!r}): only its flags change')
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
        """Marked `deleted` (# Flags): out of sight and read only until its flags are changed back. 404 when there is none."""
        row = await cls.read(id)
        row.flags |= Flags.DELETED
        await cls.db().flush()

    @classmethod
    async def list(cls, *where, order: tuple, what: str) -> Sequence[Self]:
        """A `list`, not paged: every record in sight of its table `where` selects, in `order`; refused with 422 naming their count and
        size, `what` they are, when they are more than a list sends, `LIST` rows or `LIST_BYTES` of their `data` and `meta` as stored."""
        query = select(cls).where(cls.flags.op('&')(int(UNSEEN)) == 0, *where)
        found = query.subquery()
        n, size = (await cls.db().exec(select(func.count(), func.coalesce(func.sum(func.pg_column_size(found.c.data) + func.pg_column_size(found.c.meta)), 0)))).one()
        if n > LIST or size > LIST_BYTES:
            raise HTTPException(422, f'{n} {what}, {size} bytes of data, more than a list sends ({LIST}, {LIST_BYTES} bytes): search them, a page at a time')
        return (await cls.db().exec(query.order_by(*order))).all()

    @classmethod
    async def search(cls, params, *where, conditions: QueryParams | None = None, order: tuple = (), only: bool = False):
        """A page of a search: the records in sight of its table fastapi-querybuilder's query of `conditions` and `where` select,
        `limit` of them after the last one of the page before (sqlakeyset), in the sort of `conditions`, then in `order`, then by
        the id, which no two rows share; every match when no limit is given. `only` keeps to its own table's records, not those of
        the tables made from it."""
        query = (build_query(cls, conditions) if conditions else select(cls)).where(cls.flags.op('&')(int(UNSEEN)) == 0, *where)
        if only:
            query = query.with_hint(cls.__table__, 'ONLY', 'postgresql')

        def after(key):
            """A sort key a page can read after: one a record may leave empty, a column's or a key's in `data` or `meta`, sorts that
            record as the least value of its kind, the key's when it is read as one, else its column's."""
            key = key if isinstance(key, UnaryExpression) else key.asc()
            column = next(c for c in iterate(key.element) if isinstance(c, Column))   # under querybuilder's lower() of a text column
            typed = column if isinstance(key.element.type, NullType) else key.element   # lower() has no type of its own
            if not column.nullable and typed is column:
                return key
            return UnaryExpression(func.coalesce(key.element, literal(LEAST[typed.type.python_type], typed.type)), modifier=key.modifier)
        keys = [after(k) for k in (*query._order_by_clauses, *order)]   # querybuilder's sort, then the caller's, read as sqlakeyset reads them
        query = query.order_by(None).order_by(*keys, cls.id)
        if params.size is None:
            rows = (await cls.db().scalars(query)).all()   # querybuilder's select is SQLAlchemy's: rows of one record each
            return create_page(rows, params=params, total=len(rows))
        return await apaginate(cls.db(), query, params=params)


class _Type(_Record):
    """A type's columns: its slug, unique in its shard, and the shard its records are in, shard2 of their table in its schema;
    its schema, shard1, is its own id's. A status is a type of type `status` whose parent is the type it belongs to; a type's parent
    is the type it extends, in its schema or in `ld`. Every schema's types are a table made from it."""
    # required to make a type, which its table refuses without them, not to change one: an update takes only what changes
    slug: str | None = Field(None, sa_type=String, sa_column_kwargs={'nullable': False}, description='Its slug, unique in its shard.')
    shard: int | None = Field(None, sa_type=SmallInteger, sa_column_kwargs={'nullable': False}, description='shard2 of the table its records are in, in its schema.')


class _Link(_Record):
    """A link's columns: it joins one record to another, so it has a direction."""
    from_id: UUID | None = Field(None, description='The record where it starts.')
    to_id: UUID | None = Field(None, description='The record where it ends.')

    @classmethod
    async def update(cls, id: UUID | None, sent: _Record) -> Self:
        """As a record is written; an end it is sent that is not a record is refused, and so is a type it is sent that is not one of
        its schema's types for its table, which its id says (# UUID)."""
        row = await super().update(id, sent)
        for end in (getattr(row, k) for k in ('from_id', 'to_id') if k in sent.model_fields_set):
            if end and not await cls.db().get(Record, end):   # every table inherits ld.records
                raise HTTPException(422, f'{end} is not a record')
        if 'type' in sent.model_fields_set and row.type is not None:
            types = (await cls.db().exec(select(Type.id).where(Type.slug == row.type, Type.shard == row.id.bytes[1], Type.type.is_distinct_from('status')))).all()
            if not any(t.bytes[0] == row.id.bytes[0] for t in types):   # every schema's types are read in ld.types
                raise HTTPException(422, f'{row.type!r} is not a type of the links of its schema')
        return row


class Fields(_Link):
    """A record as a caller sends it to `/records`: a record's columns and a link's ends; each table takes those it has."""


# ++     The core's tables: schema `ld`, shard1 0x00

class Record(_Record, table=True):
    """Every table inherits it, and it holds none of its own: reading `ld.records` returns every table's rows with these columns."""
    __tablename__, __table_args__ = 'records', {'schema': 'ld'}


class Type(_Type, table=True):
    """What a record is, and its statuses."""
    __tablename__, __table_args__, __shard__ = 'types', (UniqueConstraint('shard', 'slug'), {'schema': 'ld'}), 0x0000


class Node(_Record, table=True):
    """A node (vertex) or a row; most belong to a container, their `parent_id`."""
    __tablename__, __table_args__, __shard__ = 'nodes', {'schema': 'ld'}, 0x0001


class Link(_Link, table=True):
    """An edge that links two records."""
    __tablename__, __table_args__, __shard__ = 'links', {'schema': 'ld'}, 0x0010


class Event(_Record, table=True):
    """Something that happened: an `event` at one moment, an `activity` over its span."""
    __tablename__, __table_args__, __shard__ = 'events', {'schema': 'ld'}, 0x0020


def operations(path: str, body: type[_Record], name: str, *models: type[_Record]) -> APIRouter:
    """A path for its tables: create, read, update, delete and search, each table its own, `body` what a caller sends. A create's
    table is the one its `type` names (`ld.types`); a read, an update or a delete's `id` says its table by its first two bytes,
    shard1 and shard2, and one of a table the path has not is read and changed through the first, with its columns."""
    routes, base = APIRouter(tags=[name]), models[0]
    own = {m.__shard__: m for m in models if hasattr(m, '__shard__')}   # an id's first two bytes to its table
    One = Union[models]   # a record of the path, read with its own table's columns
    a, names = 'an' if name[0] in 'aeiou' else 'a', name[:-1] + 'ies' if name.endswith('y') else name + 's'   # an entity, entities

    def shard(id: UUID) -> int:
        """The table an id is in: its first two bytes, shard1 its schema and shard2 the table."""
        return int.from_bytes(id.bytes[:2])

    async def table(record: _Record) -> type[_Record]:
        """The table of the record's `type`, one of the path's: the type's own id says its schema, shard1, and its `shard` the
        table in it, shard2. Every schema's types are read in `ld.types`, which they inherit."""
        if len(own) == 1:
            return next(iter(own.values()))
        types = (await _Record.db().exec(select(Type.id, Type.shard).where(Type.slug == record.type, Type.type.is_distinct_from('status')))).all()
        if len(found := {s for id, shard2 in types if (s := id.bytes[0] << 8 | shard2) in own}) != 1:
            raise HTTPException(422, f'{record.type!r} is a type of {len(found) or "no"} table{"" if len(found) == 1 else "s"} of {path}: '
                                     + ', '.join(m.__table__.fullname for m in own.values()))
        return own[found.pop()]

    @routes.post(path, response_model=One, summary=f'Create {a} {name}')
    async def create(record: body):
        """It comes back with the `id`, `name`, `ts` and `created` the store gave it."""
        return await (await table(record)).create(record)

    @routes.get(path + '/{id}', response_model=One, summary=f'Read {a} {name}')
    async def read(id: UUID):
        """404 when there is none."""
        return await own.get(shard(id), base).read(id)

    @routes.put(path + '/{id}', response_model=One, summary=f'Update {a} {name}')
    async def update(id: UUID, record: body):
        """Merged with what is sent when the `id` is there, created with that `id` when it is not; an `id` of a table the path has
        not is refused when it is not there."""
        if shard(id) not in own and not await base.db().get(base, id):
            raise HTTPException(422, f'{path} has {", ".join(m.__table__.fullname for m in own.values())}; no record {id} is there to update')
        return await own.get(shard(id), base).update(id, record)

    @routes.delete(path + '/{id}', status_code=204, summary=f'Delete {a} {name}')
    async def delete(id: UUID):
        """Marked `deleted`: out of sight and read only until its flags are changed back. 404 when there is none."""
        await own.get(shard(id), base).delete(id)

    @routes.get(path, response_model=Page[One], summary=f'Search {names}')
    async def search(type: str | None = None, conditions: QueryParams = Depends(), params: Params = Depends()):
        """Of one `type`, or of every type, in the tables of the path with the columns of the first; records out of sight are
        not searched.

        `filters` is one JSON document of conditions on any column,
        `{"parent_id": {"$eq": "…"}, "status": {"$ne": "discarded"}, "name": {"$contains": "x"}}`, with the operators
        `$eq` `$ne` `$gt` `$gte` `$lt` `$lte` `$in` `$contains` `$startswith` `$isempty` `$isnotempty`, joined by `$and` `$or`.
        A time in a condition is UTC in whole seconds, `2026-10-16T13:00:00Z` or the same without the `Z`; one with an offset is refused.
        `sort` is `column:asc` or `column:desc`; `search` is text looked for in every text column.

        A page is `limit` records after `cursor`, with the `total` and `next`, the cursor of the page after it, none after the last.
        Every match when no `limit` is given."""
        return await base.search(params, *([base.type == type] if type else []), conditions=conditions)

    return routes


router = APIRouter()


@router.get('/records/{id}/records', response_model=list[Record], tags=['record'], summary="List a record's children")
async def record_list(id: UUID, type: str | None = None):
    """`list`, a simple select of like records: the records in sight whose parent it is, of one `type` or of every type, in the
    order they were made. No query, that is search, and not paged: more than `LIST` children, or more than `LIST_BYTES` of their
    `data` and `meta`, are refused with their count and size, and search pages them."""
    return await Record.list(Record.parent_id == id, *([Record.type == type] if type else []), order=(Record.created,), what=f'records are under {id}')


@router.get('/records/{id}/links', response_model=Page[Link], tags=['link'], summary="Search a record's links")
async def record_links(id: UUID, conditions: QueryParams = Depends(), params: Params = Depends()):
    """From it and to it; `filters`, `sort`, `search` and paging as in record search."""
    return await Link.search(params, or_(Link.from_id == id, Link.to_id == id), conditions=conditions)


router.include_router(operations('/records', Fields, 'record', Record, Node, Link, Event))
router.include_router(operations('/types', _Type, 'type', Type))
router.include_router(operations('/links', _Link, 'link', Link))


async def refusal(request: Request, e: StatementError):
    """What a table refuses, a link without an end, a type's slug taken in its shard, a value Postgres cannot hold, and a filter
    its column cannot take, an operator its type has not or a value not of its kind, is the caller's to fix: 422 with the reason.
    Any other failure is the API's own."""
    if isinstance(e, (IntegrityError, DataError)) or isinstance(e.orig, (UndefinedFunction, ValidationError)):
        return JSONResponse({'detail': str(e.orig).strip()}, status_code=422)
    raise e


app = FastAPI(
    title='Linked Data',
    version='1',   # the major version its path carries, /ld/v1 (Alex 10-16 09:48: versions in the URL)
    summary='Records and the links between them: create, read, update, delete, search.',
    openapi_tags=[
        {'name': 'record', 'description': 'Every record of every table.'},
        {'name': 'type', 'description': 'What a record can be, and its statuses.'},
        {'name': 'link', 'description': 'The links between records.'}],
)
app.include_router(router)


def api_at(path: str, name: str, summary: str, *routers: APIRouter) -> FastAPI:
    """An API built on the core, separate from it: its own paths under `path` and its own documentation there, `{path}/docs`."""
    built = FastAPI(title=f'Linked Data: {name}', version='1', summary=summary, docs_url=f'{path}/docs', openapi_url=f'{path}/openapi.json')
    for routes in routers:
        built.include_router(routes)
    return built


def serve(apis: dict[str, FastAPI], store: _SQABase) -> FastAPI:
    """The core and the APIs built on it as one API on `store`, the app's: its scoped session is every record's (`_Record.db`), set
    once here, and each request is one transaction (`transaction`). Every route in one OpenAPI document, `/openapi.json`, shown at `/docs`, each API's routes under its tag; each API built on it keeps its own
    document at `{path}/docs` as well. With no APIs, the core alone."""
    tags = {t: a.summary for a in apis.values() for ops in a.openapi()['paths'].values() for op in ops.values() for t in op.get('tags', ())}   # each API's tags, described by its summary
    one = FastAPI(title=app.title, version=app.version, summary='Records and the links between them, and the APIs built on them: '
                  + ', '.join(p.strip('/') for p in apis) + '.',
                  openapi_tags=app.openapi_tags + [{'name': t, 'description': s} for t, s in tags.items()],
                  dependencies=[Depends(transaction, scope='function')], exception_handlers={StatementError: refusal})
    one.include_router(router)
    for api in apis.values():
        one.include_router(api.router)
    _Record.db = store.scoped_session
    add_pagination(one)
    return one
