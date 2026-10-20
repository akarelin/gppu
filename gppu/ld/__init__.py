"""Linked Data: records and the links between them, on Postgres, and what an API of a type is built from (_Projects/Linked Data,
"Linked Data - Universal types, statuses and sharding", # Implementation). `_Record`, every record's columns and its operations
(# Universals, Operations: create, read, update, delete, list, search), with no table; the types that add columns or are abstract as
data models on it (`_Event`, `_Activity`, `_View`, `_Link`; `_Content`, `_Container`, `_Resource`); and each type's class, which only
defines its table: the core's (`Record`, `Node`, `Collection`, `View`, `Event`, `Message`, `Activity`, `Link`) here, a domain's in
its own module. The core's paths (`app`: `/types`, `/records`, `/links`), and for a domain's API: `typed()`, its types' paths;
`api_at()`, the API with its own documentation; `served()`, the APIs at one address. The tables are made by the store's
`schema.sql` (RAN `Projects/ld`); `connect()` opens the store.

Needs the `ld` extra, and fastapi-querybuilder installed with `--no-deps`: its metadata lists poetry, uvicorn and aiosqlite as runtime
dependencies."""
import json
import re
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from collections.abc import Sequence
from typing import Annotated, Any, ClassVar, Literal, Self, TypeVar, Union
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
from pydantic import ConfigDict, GetCoreSchemaHandler, GetJsonSchemaHandler, TypeAdapter, ValidationError, field_validator, model_validator
from pydantic_core import core_schema
from sqlakeyset import custom_bookmark_type
from sqlalchemy import DateTime, FetchedValue, SmallInteger, String, TypeDecorator, bindparam
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, Range
from sqlalchemy.exc import DataError, IntegrityError, NoResultFound, StatementError
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: F401  RAN Projects/ld's checks make their engine with ld.create_async_engine
from sqlalchemy.sql.elements import UnaryExpression
from sqlalchemy.sql.visitors import iterate
from sqlmodel import Column, Field, SQLModel, delete, func, not_, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..data import async_engine
from ..gppu import TimeSpan

T = TypeVar('T')

engine = None   # the store, opened by connect()
LIST = 1000   # the most records a list sends: the older data's largest list of like records is a folder's 585 files (work 15, a location's runs 16, 2026-10-17)
LIST_BYTES = 1_000_000   # and the most data it sends, `data` and `meta` as Postgres stores them: that folder's are 187 kB (work 45 kB; a session's messages up to 145 MB, so they are read a page at a time)
DATETIME, DURATION = TypeAdapter(datetime), TypeAdapter(timedelta)
STATUSES = ('new', 'active', 'pending', 'discarded', 'rejected', 'archived')   # every record's (the spec's Record, and # States); a type adds its own
STORE = ('id', 'created', 'updated', 'type')   # the columns Postgres fills: a caller does not send them


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


# ++     Conditions querybuilder does not read: a key inside `data` or `meta`, and a span overlapping another

INSIDE = re.compile(r'(data|meta)\.(\w[\w.-]*)')   # `data.kind`, `meta.generated.by`: a key inside a record's data or meta, by its path


def inside(model, key: str):
    """The text a record's `data` or `meta` holds at a key's path (`data.planned.end`), or None when it holds none."""
    column, path = INSIDE.fullmatch(key).groups()
    return func.jsonb_extract_path_text(getattr(model, column), *path.split('.'))


def as_text(v: Any) -> str:
    """A value as Postgres gives a JSON value's text: a string as it is, anything else as JSON writes it (`true`, `3`)."""
    return v if isinstance(v, str) else json.dumps(v)


def clauses(expr, condition: Any) -> list:
    """The clauses of one condition on a key inside data or meta: `{"$eq": "Feature"}`, or a value alone, which is `$eq`; the operators
    of record search but `$isempty` and `$isnotempty`, which read whether the key holds anything."""
    ops = condition if isinstance(condition, dict) else {'$eq': condition}
    clauses = []
    for op, v in ops.items():
        match op:
            case '$eq': clauses.append(expr == as_text(v))
            case '$ne': clauses.append(or_(expr.is_(None), expr != as_text(v)))
            case '$gt': clauses.append(expr > as_text(v))
            case '$gte': clauses.append(expr >= as_text(v))
            case '$lt': clauses.append(expr < as_text(v))
            case '$lte': clauses.append(expr <= as_text(v))
            case '$in': clauses.append(expr.in_([as_text(x) for x in v]))
            case '$contains': clauses.append(expr.ilike(f'%{v}%'))
            case '$startswith': clauses.append(expr.ilike(f'{v}%'))
            case '$isempty': clauses.append(or_(expr.is_(None), expr == ''))
            case '$isnotempty': clauses.append(not_(or_(expr.is_(None), expr == '')))
            case _: raise HTTPException(422, f'a key inside data or meta takes $eq $ne $gt $gte $lt $lte $in $contains $startswith $isempty $isnotempty, not {op}')
    return clauses


class TypeCode(TypeDecorator):
    """A record's `type` as Postgres computes it from the `id` (schema.sql), read as the `Type` it names."""
    impl = SmallInteger
    cache_ok = True

    def process_result_value(self, value, dialect):
        return None if value is None else Type(value) if value in Type else value   # a link's 0xA1 to 0xAF have no name in record_types


# ++     _Record: every record's columns and its operations; a type's class only defines its table

class _Record(SQLModel):
    """Everything stored is a record (# Record), and every type is built on it: its columns and its operations (# Universals,
    Operations), with no table of its own. A type's class is made from it, or from a data model on it, and only defines its table,
    `class Node(_Record, table=True)`, so it is created, read, updated, deleted, listed and searched in its own table by its own
    rules. What a caller sends is a record without the columns Postgres fills (`STORE`); a field its type has not is refused."""
    model_config = ConfigDict(extra='forbid')
    __mapper_args__ = {'eager_defaults': True}   # the id, type and times the table makes come back with the insert
    id: UUID | None = Field(None, primary_key=True, sa_column_kwargs={'server_default': FetchedValue()},
                            description="The record's identity in this system; its first byte is the `type`.")
    # DateTime, not SQLModel's own: filters read a time they are given only for DateTime columns
    created: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'server_default': FetchedValue(), 'nullable': False}, description='When the record was made.')
    updated: datetime | None = Field(None, sa_type=DateTime(timezone=True), sa_column_kwargs={'onupdate': func.now()}, description='When the record was last changed.')
    type: Type | int | None = Field(None, sa_type=TypeCode, sa_column_kwargs={'server_default': FetchedValue()}, description='What the record is: the first byte of its `id`. Read only.')
    # String, not SQLModel's own AutoString: search looks for its text only in String columns
    subtype: str | None = Field(None, sa_type=String, description='Plain text refining the `type`, from a short list per type that Postgres does not enforce.')
    status: str | None = Field(None, sa_type=String, description='Slug: ' + ', '.join(f'`{s}`' for s in STATUSES) + ' on any record, or one its type adds; any other is refused.')
    name: str | None = Field(None, sa_type=String, description='Name used for display.')
    data: dict = Field(default_factory=dict, sa_type=JSONB, description='What the record says about the thing. On update, merged into what is there; a null removes a key.')
    meta: dict = Field(default_factory=dict, sa_type=JSONB, description='How the record came to be: who made it, from what, when it was seen. `meta.tags`: always a list of strings. Merged on update as `data` is.')
    parent_id: UUID | None = Field(None, description='The container the record belongs to.')
    STATUSES: ClassVar[tuple[str, ...]] = ()   # the statuses its type adds to every record's
    PARENTS: ClassVar[tuple[Type, ...]] = ()   # the types its parent is, where the spec names them; else any container
    CODES: ClassVar[range | None] = None   # the first bytes its ids take where they are more than its type's code: a link's 0xA0 to 0xAF

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

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler) -> dict:
        """What a caller sends is a record without the columns Postgres fills; what the API answers has them."""
        json_schema = handler(schema)
        if handler.mode == 'validation':
            for key in STORE:
                handler.resolve_ref_schema(json_schema).get('properties', {}).pop(key, None)
        return json_schema

    @classmethod
    async def create(cls, db: AsyncSession, sent: '_Record') -> Self:
        """A new record of its type from what is sent, with the id the store makes. Stored at the commit."""
        return await cls.update(db, None, sent)

    @classmethod
    async def read(cls, db: AsyncSession, id: UUID) -> Self:
        """404 when there is none (`missing`)."""
        return await db.get_one(cls, id)

    @classmethod
    async def update(cls, db: AsyncSession, id: UUID | None, sent: '_Record') -> Self:
        """Merged into the record of that id when it is there, `data` and `meta` merged and a null removing a key; created with that id
        when it is not: an insert is an upsert. Stored at the commit. The columns Postgres fills, a field its table has not (an event's
        `ts` sent to a node), an id of another type, a status its type has not and a parent that is not a container its type may be in
        are refused."""
        if filled := sent.model_fields_set & set(STORE):
            raise HTTPException(422, f'{", ".join(sorted(filled))}: the store fills them')
        if extra := sent.model_fields_set - cls.model_fields.keys():
            raise HTTPException(422, f'a {cls.__tablename__} has no {", ".join(sorted(extra))}')
        if id and (row := await db.get(cls, id)):
            kind = table(row.type)   # its own type's rules, also when it is written as the type it is read as: a task through /records
            kind.check_status(sent)
            change = {k: getattr(sent, k) for k in sent.model_fields_set}   # what was sent, a span still a Span
            for key in ('data', 'meta'):
                if key in change:
                    change[key] = {k: v for k, v in (getattr(row, key) | change[key]).items() if v is not None}
            row = row.sqlmodel_update(change)
        else:
            if id and tables().get(id.bytes[0]) is not cls:   # an id's first byte is its type: a file's id would make a record in the wrong table
                raise HTTPException(422, f'{id} is of type {id.bytes[0]:#04x}, which this path does not make')
            kind = cls
            kind.check_status(sent)
            row = cls.model_validate(sent, update={'id': id})
            db.add(row)
        if 'parent_id' in sent.model_fields_set and row.parent_id:
            await kind.check_parent(db, row)
        return row

    @classmethod
    async def delete(cls, db: AsyncSession, id: UUID) -> None:
        """With the links from it and to it; refused while it holds records, which are deleted or moved out first. 404 when there is
        none. Gone at the commit."""
        await cls.read(db, id)
        if n := (await db.exec(select(func.count()).select_from(Record).where(Record.parent_id == id))).one():
            raise HTTPException(422, f'{id} holds {n} records: delete them or move them out first')
        await db.execute(delete(Link).where(or_(Link.from_id == id, Link.to_id == id)))
        await db.execute(delete(cls).where(cls.id == id))

    @classmethod
    async def list(cls, db: AsyncSession, *where, order: tuple, what: str) -> Sequence[Self]:
        """A `list` (# Universals, Operations), not paged: every record of its table `where` selects, in `order`; refused with 422
        naming their count and size, `what` they are, when they are more than a list sends, `LIST` rows or `LIST_BYTES` of their
        `data` and `meta` as stored."""
        query = select(cls).where(*where)
        found = query.subquery()
        n, size = (await db.exec(select(func.count(), func.coalesce(func.sum(func.pg_column_size(found.c.data) + func.pg_column_size(found.c.meta)), 0)))).one()
        if n > LIST or size > LIST_BYTES:
            raise HTTPException(422, f'{n} {what}, {size} bytes of data, more than a list sends ({LIST}, {LIST_BYTES} bytes): search them, a page at a time')
        return (await db.exec(query.order_by(*order))).all()

    @classmethod
    async def search(cls, db: AsyncSession, params, *where, conditions: QueryParams | None = None, only: bool = False):
        """A page of a search (# Universals, Operations): the records of its table `conditions` find (`find`) and `where` selects,
        `limit` of them after the last one of the page before (sqlakeyset), so the order ends with the id, which no two rows share;
        every match when no limit is given. `only` keeps to its own table's records, not those of the types made from it."""
        query = (cls.find(conditions) if conditions else select(cls)).where(*where)
        if only:
            query = query.with_hint(cls.__table__, 'ONLY', 'postgresql')

        def after(key):
            """A sort key a page can read after: one over a column a record may leave empty sorts that record as the column's least value."""
            column = next(c for c in iterate(key.element) if isinstance(c, Column))   # under querybuilder's lower() of a text column
            return UnaryExpression(func.coalesce(key.element, LEAST[column.type.python_type]), modifier=key.modifier) if column.nullable else key
        keys = [after(k) for k in query._order_by_clauses]   # querybuilder's sort, read as sqlakeyset reads it
        query = query.order_by(None).order_by(*keys, cls.id)
        if params.size is None:
            rows = (await db.scalars(query)).all()   # querybuilder's select is SQLAlchemy's: rows of one record each
            return create_page(rows, params=params, total=len(rows))
        return await apaginate(db, query, params=params)

    @classmethod
    def find(cls, conditions: QueryParams):
        """The select of a search: querybuilder's, of the conditions it reads, and of the two it does not, each at the top of `filters`:
        a key inside `data` or `meta`, `{"data.kind": {"$eq": "Feature"}}`, and a span overlapping a span, `{"span": {"$overlaps":
        {"start": "…", "end": "…"}}}`, in any of a span's forms, an end left out an open one."""
        try:
            sent = json.loads(conditions.filters) if conditions.filters else {}
        except json.JSONDecodeError as e:
            raise HTTPException(422, f'filters is not JSON: {e}')
        if not isinstance(sent, dict):
            raise HTTPException(422, 'filters is a JSON object of conditions')
        ours = {k: v for k, v in sent.items() if INSIDE.fullmatch(k) or (k == 'span' and isinstance(v, dict) and '$overlaps' in v)}
        rest = {k: v for k, v in sent.items() if k not in ours}
        query = build_query(cls, QueryParams(json.dumps(rest) if rest else None, conditions.sort, conditions.search, conditions.search_fields, conditions.case_sensitive))
        for key, condition in ours.items():
            if key == 'span':
                if not hasattr(cls, 'span'):
                    raise HTTPException(422, f'a {cls.__tablename__} has no span')
                span = SPAN.validate_python(condition['$overlaps'])
                query = query.where(cls.span.op('&&')(bindparam(None, span, type_=SpanColumn())))
            else:
                query = query.where(*clauses(inside(cls, key), condition))
        return query

    @classmethod
    def check_status(cls, sent: '_Record'):
        """A status is every record's (`STATUSES`) or one its type adds; any other is refused."""
        if sent.status not in (None, *STATUSES, *cls.STATUSES):
            raise HTTPException(422, f"a {cls.__tablename__}'s status is {', '.join(STATUSES + cls.STATUSES)}, not {sent.status}")

    @classmethod
    async def check_parent(cls, db: AsyncSession, row: '_Record'):
        """A record's parent is a container (`_Container`), of a type its own type may be in where the spec names one (`PARENTS`), and
        neither the record itself nor a record it holds: containers nest."""
        if not (parent := await db.get(Record, row.parent_id)):   # every table inherits record: a record of any type
            raise HTTPException(422, f'no record {row.parent_id} to hold it')
        holder = table(parent.type)
        if cls.PARENTS and parent.type not in cls.PARENTS:
            raise HTTPException(422, f"a {cls.__tablename__}'s parent is a {' or a '.join(t.name.lower() for t in cls.PARENTS)}, not a {holder.__tablename__}")
        if not issubclass(holder, _Container):
            raise HTTPException(422, f'{parent.id} is a {holder.__tablename__}, not a container')
        seen, at = set(), parent
        while at and at.id not in seen:   # up the containers it would be in
            if at.id == row.id:
                raise HTTPException(422, f'{row.id} would be in itself')
            seen.add(at.id)
            at = at.parent_id and await db.get(Record, at.parent_id)


def tables() -> dict:
    """Every type's table class imported, by its type's code, `Type` named as its table is; a link's 0xA0 to 0xAF are all link's.
    A domain's are those of its module once it is imported."""
    found, todo = {}, [_Record]
    while todo:
        cls = todo.pop()
        todo += cls.__subclasses__()
        if hasattr(cls, '__table__'):
            found |= dict.fromkeys(cls.CODES or (Type[cls.__tablename__.upper()],), cls)
    return found


def table(code: int):
    """The class of the table a type is made in, wherever it is defined: work's and sessions' are outside gppu."""
    if not (found := tables().get(code)):
        raise RuntimeError(f'no table here makes type {code:#04x}: the module that makes it is not imported')
    return found


# ++     The data models: what a type adds to a record, and the abstract types

class _Link(_Record):
    """A link's columns: it joins one node to another, so it has a direction. Its ids are 0xA0 to 0xAF (`LINKS`)."""
    CODES = LINKS
    from_id: UUID | None = Field(None, description='The node where it starts.')
    to_id: UUID | None = Field(None, description='The node where it ends.')

    @classmethod
    async def update(cls, db: AsyncSession, id: UUID | None, sent: _Record) -> Self:
        """As a record is written; an end it is sent that is not a node is refused."""
        row = await super().update(db, id, sent)
        for end in (getattr(row, k) for k in ('from_id', 'to_id') if k in sent.model_fields_set):
            if end and not await db.get(Node, end):   # node's table inherits every type but record and link
                raise HTTPException(422, f'{end} is not a node')
        return row


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


class _Content(_Record):
    """A record that is the content itself, held in the record, where a resource only points to something outside."""


class _Container(_Record):
    """A record that other records belong to through their `parent_id`. A record's parent is a container."""


class _Resource(_Container):
    """A container that points to something outside Linked Data, reached rather than stored."""


# ++     The core's types: each its table

class Record(_Record, table=True):
    """Everything stored is a record, and every type is built on it: reading `record` returns every type's rows with these columns."""


class Node(_Record, table=True):
    """A record that links join and that can hold other records: every type but record and link."""


class Collection(_Record, table=True):
    """A node that groups the nodes linked to it; one node can be in many collections."""


class View(_View, _Container, table=True):
    """A container that holds a query against external data and when it was last run, so its result can be refreshed."""


class Event(_Event, table=True):
    """Something that happened at one moment, `ts`."""


class Message(_Event, _Content, table=True):
    """An event that is also content: content with the one moment it happened, `ts`."""


class Activity(_Activity, table=True):
    """A named timespan."""


class Link(_Link, table=True):
    """A record that joins one node to another, so it has a direction; its id is 0xA0 to 0xAF (`LINKS`)."""


CORE = (Record, Node, Collection, View, Event, Message, Activity, Link)   # the types the core makes, each in its own table
READ = {code: t for code, t in tables().items() if t in CORE} | {
    Type.CONTENT: Node, Type.RESOURCE: Node, Type.CONTAINER: Node, Type.FS_NODE: Node, Type.FS_LOCATION: Node, Type.FS_FILE: Node,
    Type.FS_INDEX: Node, Type.SESSION: Activity, Type.SESSION_MESSAGE: Message, Type.WORK: Activity, Type.TASK: Activity,
    Type.PROJECT: Activity}   # and the others, read with the columns of the type each is made from
AnyRecord = Union[CORE]   # a record read with the columns of its type's table


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
    statuses: list[str] = Field(description="The statuses its records take: every record's, then those its type adds.")


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
    imported = tables()   # a type's statuses are its table's where its module is imported
    return [TypeRead(**t.model_dump(), read_as=READ.get(t.id, Record).__name__, statuses=list(STATUSES + (imported[t.id].STATUSES if t.id in imported else ())))
            for t in rows]


# ++     What controls read: a field's values, a tree a level at a time, a record's parents, the records linked to it, its neighbourhood

class Value(SQLModel):
    """A value a field holds, and how many records hold it."""
    value: Any = Field(description='The value; null for the records that hold none.')
    records: int = Field(description='How many of the records found hold it.')


VALUED = ('type', 'subtype', 'status', 'name', 'parent_id')   # the columns whose values a control offers; a key inside data or meta is reached by its path


@router.get('/records/values', response_model=list[Value], tags=['records'], summary="List a field's values")
async def values(db: Db, field: str, type: Type | None = None, conditions: QueryParams = Depends()):
    """The values `field` holds among the records `type`, `filters` and `search` find (as in record search), each with how many
    records hold it, most first: what a dropdown, a selector or a filter offers. `field` is a column, `type`, `subtype`, `status`,
    `name` or `parent_id`, or a key inside data or meta by its path, `data.kind`. A `list`: more values than a list sends are refused."""
    model = READ.get(type, Record)
    query = model.find(conditions)
    found = (query.where(model.type == type) if type else query).order_by(None).subquery()
    if INSIDE.fullmatch(field):
        value = inside(found.c, field)
    elif field in VALUED:
        value = found.c[field]
    else:
        raise HTTPException(422, f"a field is {', '.join(VALUED)} or a key inside data or meta, data.kind; not {field}")
    counted = select(value.label('value'), func.count().label('records')).group_by(value)
    if (n := (await db.exec(select(func.count()).select_from(counted.subquery()))).one()) > LIST:
        raise HTTPException(422, f'{field} holds {n} values, more than a list sends ({LIST}): search the records')
    return [Value(value=v, records=c) for v, c in (await db.exec(counted.order_by(func.count().desc(), value))).all()]


class Held(SQLModel):
    """A record in a tree, and how many records it holds, so a tree control knows which to offer to open."""
    record: AnyRecord = Field(description='The record, with the columns of its type.')
    holds: int = Field(description='How many records it holds: those whose parent it is.')


async def holding(db: AsyncSession, rows: list) -> list[Held]:
    counts = dict((await db.exec(select(Record.parent_id, func.count()).where(Record.parent_id.in_([r.id for r in rows])).group_by(Record.parent_id))).all()) if rows else {}
    return [Held(record=r, holds=counts.get(r.id, 0)) for r in rows]


@router.get('/records/tree', response_model=list[Held], tags=['records'], summary="List a type's roots")
async def roots(db: Db, type: Type):
    """The records of a `type` that are in no container, by name, each with how many records it holds: the top of a tree control.
    A `list`."""
    model = READ.get(type, Record)
    return await holding(db, await model.list(db, model.type == type, model.parent_id.is_(None), order=(model.name, model.id), what=f'{type.name.lower()}s are roots'))


@router.post('/records', response_model=AnyRecord, tags=['records'], summary='Create a record')
async def record_create(db: Db, record: Fields, type: Type = Type.RECORD):
    """Of the `type` given, in its type's table: a record, a node, a collection, a view with its `query`, an event or a message with
    its `ts`, an activity with its `span`. It comes back with the `id`, `type` and `created` the store gave it."""
    if (model := tables().get(type)) not in CORE:
        raise HTTPException(422, f'the core does not make a {type.name.lower()}')
    return await saved(db, await model.create(db, record))


@router.get('/records/{id}', response_model=AnyRecord, tags=['records'], summary='Read a record')
async def record_read(db: Db, id: UUID):
    """With the columns of its type's table, the `id` saying its type; a domain's type, with those of the type it is made from (a
    session's `span`, a session message's `ts`). 404 when there is none."""
    return await READ.get(id.bytes[0], Record).read(db, id)


@router.put('/records/{id}', response_model=AnyRecord, tags=['records'], summary='Update a record')
async def record_update(db: Db, id: UUID, record: Fields):
    """Merged with what is sent when the `id` is there, created with that `id` when it is not. Fields not sent are left as they are.
    The `id` says its type, so its table; a domain's type is updated in the columns it is read with."""
    return await saved(db, await READ.get(id.bytes[0], Record).update(db, id, record))


@router.get('/records', response_model=Page[AnyRecord], tags=['records'], summary='Search records')
async def record_search(db: Db, type: Type | None = None, conditions: QueryParams = Depends(), params: Params = Depends()):
    """Of one `type`, with the columns it is read with, or of every type, with the record columns.

    `filters` is one JSON document of conditions on any column,
    `{"parent_id": {"$eq": "…"}, "status": {"$ne": "discarded"}, "name": {"$contains": "x"}}`, with the operators
    `$eq` `$ne` `$gt` `$gte` `$lt` `$lte` `$in` `$contains` `$startswith` `$isempty` `$isnotempty`, joined by `$and` `$or`.
    A time in a condition is UTC in whole seconds, `2026-10-16T13:00:00Z` or the same without the `Z`; one with an offset is refused.
    A key inside `data` or `meta` is reached by its path, `{"data.kind": {"$eq": "Feature"}}`, `{"data.planned.end": {"$lt": "2026-11"}}`,
    compared as text; an activity's span by the spans it overlaps, `{"span": {"$overlaps": {"start": "…", "end": "…"}}}`: both at
    the top of `filters`, joined to the rest by and.
    `sort` is `column:asc` or `column:desc`; `search` is text looked for in every text column.

    A page is `limit` records after `cursor`, with the `total` and `next`, the cursor of the page after it, none after the last.
    Every match when no `limit` is given."""
    model = READ.get(type, Record)   # the type's table, or the one it is made from
    return await model.search(db, params, *([model.type == type] if type else []), conditions=conditions)


@router.get('/records/{id}/records', response_model=list[AnyRecord], tags=['records'], summary="List a record's children")
async def record_list(db: Db, id: UUID, type: Type | None = None):
    """`list`, a simple select of like records (# Universals, Operations): the records whose parent it is, in the order they were
    made, of one `type` with the columns it is read with, or of every type with the record columns. No query, that is search, and
    not paged: more than `LIST` children, or more than `LIST_BYTES` of their `data` and `meta`, are refused with their count and
    size, and search pages them."""
    model = READ.get(type, Record)
    return await model.list(db, model.parent_id == id, *([model.type == type] if type else []), order=(model.created,), what=f'records are under {id}')


@router.get('/records/{id}/tree', response_model=list[Held], tags=['records'], summary="List a record's children for a tree")
async def record_tree(db: Db, id: UUID, type: Type | None = None):
    """The records whose parent it is, of one `type` or of every type, by name, each with how many records it holds: a level of a
    tree control, opened a level at a time. A `list`."""
    model = READ.get(type, Record)
    return await holding(db, await model.list(db, model.parent_id == id, *([model.type == type] if type else []), order=(model.name, model.id), what=f'records are under {id}'))


@router.get('/records/{id}/parents', response_model=list[AnyRecord], tags=['records'], summary="Read a record's parents")
async def record_parents(db: Db, id: UUID):
    """Up the containers it is in: its parent first, then that one's, to the top, each with the columns of its type; what a
    breadcrumb draws. 404 when there is no such record."""
    chain, seen, row = [], {id}, await READ.get(id.bytes[0], Record).read(db, id)
    while row.parent_id and row.parent_id not in seen and (row := await db.get(READ.get(row.parent_id.bytes[0], Record), row.parent_id)):
        seen.add(row.id)
        chain.append(row)
    return chain


async def records_of(db: AsyncSession, ids) -> dict[UUID, Any]:
    """The records of these ids, each read with the columns of its type, by id."""
    by_type: dict[type, list] = {}
    for i in ids:
        by_type.setdefault(READ.get(i.bytes[0], Record), []).append(i)
    return {r.id: r for model, some in by_type.items() for r in (await db.exec(select(model).where(model.id.in_(some)))).all()}


class Linked(SQLModel):
    """A record at the other end of a node's link, with the link."""
    link: Link = Field(description='The link.')
    record: AnyRecord = Field(description='The node at its other end, with the columns of its type.')


@router.get('/records/{id}/linked', response_model=list[Linked], tags=['links'], summary='List the records linked to a node')
async def record_linked(db: Db, id: UUID, direction: Literal['from', 'to'] | None = None, subtype: str | None = None, type: Type | None = None):
    """The nodes at the other end of its links, each with its link, in the order the links were made: `direction` `from`, the links
    it starts, `to`, those that end at it (a collection's members, the work collected into a project), both when left out; `subtype`
    the links' subtype, an empty one (`subtype=`) the links that have none; `type` the type of the records at the other end. A `list`."""
    ends = {'from': [Link.from_id == id], 'to': [Link.to_id == id]}.get(direction, [or_(Link.from_id == id, Link.to_id == id)])
    which = [] if subtype is None else [Link.subtype.is_(None)] if subtype == '' else [Link.subtype == subtype]
    links = await Link.list(db, *ends, *which, order=(Link.created, Link.id), what=f'links are at {id}')
    other = {l.id: l.to_id if l.from_id == id else l.from_id for l in links}
    found = await records_of(db, set(other.values()))
    return [Linked(link=l, record=found[other[l.id]]) for l in links if other[l.id] in found and (type is None or found[other[l.id]].type == type)]


class Graph(SQLModel):
    """Nodes and the links between them."""
    nodes: list[AnyRecord] = Field(description='The nodes, each with the columns of its type.')
    links: list[Link] = Field(description='The links between them.')


@router.get('/records/{id}/graph', response_model=Graph, tags=['links'], summary="Read a node's neighbourhood")
async def record_graph(db: Db, id: UUID, depth: int = Query(1, ge=1, le=3, description='How many links away from it.')):
    """The node, the nodes up to `depth` links away from it and the links between them: what a graph control draws around a record.
    Refused, with their count, when they are more than a list sends."""
    await READ.get(id.bytes[0], Record).read(db, id)
    seen, frontier, links = {id}, {id}, {}
    for _ in range(depth):
        if not frontier:
            break
        for l in (await db.exec(select(Link).where(or_(Link.from_id.in_(frontier), Link.to_id.in_(frontier))))).all():
            links[l.id] = l
        reached = {e for l in links.values() for e in (l.from_id, l.to_id)}
        frontier, seen = reached - seen, seen | reached
        if len(seen) > LIST or len(links) > LIST:
            raise HTTPException(422, f'{len(seen)} nodes and {len(links)} links within {depth} of {id}, more than a list sends ({LIST}): ask for fewer links away')
    found = await records_of(db, seen)
    return Graph(nodes=list(found.values()), links=list(links.values()))


@router.delete('/records/{id}', status_code=204, tags=['records'], summary='Delete a record')
async def record_delete(db: Db, id: UUID):
    """Of any type, from its type's table, with its links; refused while it holds records. 404 when there is none."""
    await table(id.bytes[0]).delete(db, id)
    await db.commit()


@router.get('/records/{id}/links', response_model=Page[Link], tags=['links'], summary="Search a node's links")
async def record_links(db: Db, id: UUID, conditions: QueryParams = Depends(), params: Params = Depends()):
    """From it and to it; `filters`, `sort`, `search` and paging as in record search."""
    return await Link.search(db, params, or_(Link.from_id == id, Link.to_id == id), conditions=conditions)


@router.get('/links', response_model=Page[Link], tags=['links'], summary='Search links')
async def link_search(db: Db, conditions: QueryParams = Depends(), params: Params = Depends()):
    """`filters` on any of a link's columns, `from_id` and `to_id` among them, and on keys inside its data and meta; `sort`, `search`
    and paging as in record search."""
    return await Link.search(db, params, conditions=conditions)


@router.post('/links', response_model=Link, tags=['links'], summary='Create a link')
async def link_create(db: Db, record: _Link):
    """It needs `from_id` (its creator) and `to_id`."""
    return await saved(db, await Link.create(db, record))


@router.get('/links/{id}', response_model=Link, tags=['links'], summary='Read a link')
async def link_read(db: Db, id: UUID):
    """404 when there is none."""
    return await Link.read(db, id)


@router.put('/links/{id}', response_model=Link, tags=['links'], summary='Update a link')
async def link_update(db: Db, id: UUID, record: _Link):
    """As a record is updated: merged when the `id` is there, created when it is not."""
    return await saved(db, await Link.update(db, id, record))


@router.delete('/links/{id}', status_code=204, tags=['links'], summary='Delete a link')
async def link_delete(db: Db, id: UUID):
    """The link alone; the nodes at its ends stay. 404 when there is none."""
    await Link.delete(db, id)
    await db.commit()


def typed(path: str, body: type[_Record], name: str, *models: type[_Record]) -> APIRouter:
    """A domain's path for its types: create, read, update, delete and search, each type in its own table, `body` what a caller sends.
    A path of several types takes the `type` a create makes, the first by default, and the one a search reads, every one of them by
    default; a read, an update or a delete's `id` says its type."""
    routes, base = APIRouter(tags=[name]), models[0]
    own = {code: m for code, m in tables().items() if m in models}
    One = Union[models]   # a record of the path, read with its own type's columns

    def named(type: Type | None = None):
        """The table of the `type` named, one of the path's."""
        if type is not None and type not in own:
            raise HTTPException(422, f'{path} has {", ".join(t.name.lower() for t in own)}, not {type.name.lower()}')
        return type and own[type]
    kind = named if len(models) > 1 else lambda: base

    @routes.post(path, response_model=One, summary=f'Create a {name}')
    async def create(db: Db, record: body, model=Depends(kind)):
        """It comes back with the `id`, `type` and `created` the store gave it."""
        return await saved(db, await (model or base).create(db, record))

    @routes.get(path + '/{id}', response_model=One, summary=f'Read a {name}')
    async def read(db: Db, id: UUID):
        """404 when there is none."""
        return await own.get(id.bytes[0], base).read(db, id)

    @routes.put(path + '/{id}', response_model=One, summary=f'Update a {name}')
    async def update(db: Db, id: UUID, record: body):
        """Merged with what is sent when the `id` is there, created with that `id` when it is not."""
        return await saved(db, await own.get(id.bytes[0], base).update(db, id, record))

    @routes.delete(path + '/{id}', status_code=204, summary=f'Delete a {name}')
    async def remove(db: Db, id: UUID):
        """With its links; refused while it holds records, which are deleted or moved out first. 404 when there is none."""
        await own.get(id.bytes[0], base).delete(db, id)
        await db.commit()

    @routes.get(path, response_model=Page[One], summary=f'Search {name}s')
    async def search(db: Db, conditions: QueryParams = Depends(), params: Params = Depends(), model=Depends(kind)):
        """`filters`, `sort`, `search` and paging as in record search: of a type, its own table's records, not those of the types made
        from it; of every type of the path, with the columns of the first."""
        return await (model or base).search(db, params, conditions=conditions, only=bool(model))

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


def served(apis: dict[str, FastAPI]) -> FastAPI:
    """The core and the APIs built on it as one API: every route in one OpenAPI document, `/openapi.json`, shown at `/docs`, each
    API's routes under its tag; each API built on it keeps its own document at `{path}/docs` as well."""
    tags = {t: a.summary for a in apis.values() for ops in a.openapi()['paths'].values() for op in ops.values() for t in op.get('tags', ())}   # each API's tags, described by its summary
    one = FastAPI(title=app.title, version=app.version, summary='Records and the links between them, and the APIs built on them: '
                  + ', '.join(p.strip('/') for p in apis) + '.',
                  openapi_tags=app.openapi_tags + [{'name': t, 'description': s} for t, s in tags.items()])
    one.include_router(router)
    for api in apis.values():
        one.include_router(api.router)
    return handled(one)
