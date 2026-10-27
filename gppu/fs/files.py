"""The file system's records (_Standards/Linked Data, # fs): schema `fs`, shards 0x10-0x1F, built on Linked Data's record
(gppu.ld) and served at /ld/v1/fs, documented at /ld/v1/fs/docs.

A location is one place in the configured hierarchy, its provider how its data is reached and listed; a file is a file or a
folder in a location, its type its handler; an instance is what one source read of a file. Each is created, read, updated,
deleted and searched at its own path, `/fs/locations`, `/fs/files` and `/fs/instances`, and the
file system's types at `/fs/types`; gppufs makes its catalog from the locations (gppu.fs.gppufs)."""
from sqlmodel import Field, String

from ..ld import _Record, _Type, api_at, operations


class Type(_Type, table=True):
    """The file system's types and statuses: a provider's and a handler's `data.class` is the Python class that is it."""
    __tablename__, __table_args__, __shard__ = 'types', {'schema': 'fs'}, 0x10


class _Location(_Record):
    """A location's columns."""
    provider: str | None = Field(None, sa_type=String, description='Slug of its provider: how its data is reached and listed.')
    service: str | None = Field(None, sa_type=String, description='Slug of its service.')


class Location(_Location, table=True):
    """One place in the configured hierarchy. Its `parent_id` is the location it is part of."""
    __tablename__, __table_args__, __shard__ = 'locations', {'schema': 'fs'}, 0x11


class File(_Record, table=True):
    """A file or a folder in a location, known by its name in the folder it is in. Its `parent_id` is the file it is in, or the
    location at whose root it is. Its `type` is its handler; its `status` none once probed, `parsed` once its handler has read it,
    `unread` when its handler could not. `data.extension` its extension, `data.fingerprints` what identifies its content, each
    source's."""
    __tablename__, __table_args__, __shard__ = 'files', {'schema': 'fs'}, 0x13


class Instance(_Record, table=True):
    """What one source read of a file. Its `parent_id` is the file; its `span` from when the source read it to when the source
    found it gone. `data.source` the source that read it; `data.size`, `data.files`, `data.folders` its size, and for a folder what
    it holds; `data.changed_at` when the source last changed it; `data.metadata` what the handlers read of it."""
    __tablename__, __table_args__, __shard__ = 'instances', {'schema': 'fs'}, 0x14


app = api_at('/fs', 'fs', 'The file systems: their locations, files and what each source read of them.',
             operations('/fs/types', _Type, 'fs type', Type),
             operations('/fs/locations', _Location, 'location', Location),
             operations('/fs/files', _Record, 'file', File),
             operations('/fs/instances', _Record, 'instance', Instance))
