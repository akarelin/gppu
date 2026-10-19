"""Linked Data's annotations API: an `annotation` groups or classifies records, any of them linked to it, and its children are
annotations, so annotations make trees under the ones they start from ("Ideas", then "Sports" under it) and the records linked to
each are its index (_Conventions/Linked Data.md, # Annotation). Separate from the core and built on it (gppu.ld); served at
/ld/v1/annotations, documented at /ld/v1/annotations/docs. A record is linked to an annotation the core's way, `POST /links`."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_querybuilder import QueryBuilder
from sqlalchemy import String
from sqlmodel import Field, select

from . import Db, Link, Params, Page, Record, RecordFields, Stored, api_at, paged, typed

SUBTYPES = {   # how what an annotation groups is together (proposed 2026-10-18)
    'physical': 'together in the world: a drawer, a desk, a device and what is plugged into it',
    'virtual': 'held together by a system: a folder, a stack, a pairing, a channel',
    'assigned': 'put together by a person: a category, a tag, a project, a list',
    'inferred': 'found together from data: a cluster, duplicates, what is always seen together',
}


class AnnotationFields(RecordFields):
    """An annotation as a caller sends it: create sends its fields, update sends what changes."""
    subtype: Literal[*SUBTYPES] | None = Field(None, sa_type=String, description='How what it groups is together: ' + '; '.join(f'`{k}` {v}' for k, v in SUBTYPES.items()) + '.')
    parent_id: UUID | None = Field(None, description='The annotation it is under; none for one a tree starts from. A new `parent_id` is a move.')


class Annotation(AnnotationFields, Stored, table=True):
    """A grouping or a classification, its `subtype` saying how what it groups is together; its parent is an annotation too. Path: `/annotations`."""


routes = APIRouter(tags=['annotation'])


@routes.get('/annotations/{id}/records', response_model=Page[Record], summary="Search an annotation's records")
async def records(db: Db, id: UUID, query=QueryBuilder(Record), params: Params = Depends()):
    """Its index: the records linked to it, from either end of the link, of every type with the record columns; `filters`, `sort`,
    `search` and paging as in record search. The annotations under it are its children, `/records/{id}/records`. 404 when there is none."""
    await Annotation.read(db, id)
    ends = select(Link.from_id).where(Link.to_id == id).union(select(Link.to_id).where(Link.from_id == id))
    return await paged(db, query.where(Record.id.in_(ends)), Record, params)


app = api_at('/annotations', 'annotations', 'Groupings and classifications: annotations in trees, and the records linked to each, its index.',
             routes, typed('/annotations', Annotation, AnnotationFields, 'annotation'))
