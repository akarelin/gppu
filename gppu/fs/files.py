"""The file system's records (_Standards/Linked Data/Linked Data.md, # fs): schema `fs`, shard1 0x10, built on Linked Data's record
(gppu.ld) and served at /ld/v1/fs, documented at /ld/v1/fs/docs.

A location is one place in the configured hierarchy, a host among them; a file is a file or a folder in a location, its type its
handler; an instance is one copy of a file at one path, what gppufs indexes; a link joins a location or a file to a record of another schema. Each is
created, read, updated, deleted and searched at its own path, `/fs/locations`, `/fs/files`, `/fs/instances` and `/fs/links`, and
the file system's types at `/fs/types`; gppufs makes its catalog from the locations (gppu.fs.catalog)."""
from ..ld import _Link, _Record, _Type, api_at, operations


class Type(_Type, table=True):
    """The file system's types and values."""
    __tablename__, __table_args__, __shard__ = 'types', {'schema': 'fs'}, 0x1000


class Location(_Record, table=True):
    """One place in the configured hierarchy; a host is a location. Its `parent_id` is the location it is part of, and a location
    is a container: the locations and files in it have it as their `parent_id`. `status` `active` while it is in use. It is known
    by its id; `meta.display_name` its name, `meta.uri` its URI; `data.icon` how it is shown; `data.handler.access` its path on a
    host its URI does not name."""
    __tablename__, __table_args__, __shard__ = 'locations', {'schema': 'fs'}, 0x1001


class File(_Record, table=True):
    """A file or a folder in a location, known by its name in the folder it is in, `meta.display_name`. Its `parent_id` is the file
    it is in, or the location at whose root it is; an archive's members have it as their `parent_id` and are `ro`; a file an ignore
    pattern matched is `hidden`. Its `type` is its handler, which probing gives from its path, its name or its suffix. `status`
    `parsed` once its handler has read it; `data.unread` why its handler could not; `data.extension` its extension;
    `data.fingerprints` what identifies its content, each source's."""
    __tablename__, __table_args__, __shard__ = 'files', {'schema': 'fs'}, 0x1002


class Instance(_Record, table=True):
    """One copy of a file at one path, what gppufs indexes. Its `parent_id` is the file; its `span` from when the source read it to when the source
    found it gone. `kind` `symlink`, `junction` or `offline` for a copy no handler reads; `data.target` a symlink's or a junction's
    target. `data.source` the source that read it; `data.size`, `data.files`, `data.folders` its size, and for a folder what
    it holds; `data.changed_at` when the source last changed it; `data.metadata` what the handlers read of it."""
    __tablename__, __table_args__, __shard__ = 'instances', {'schema': 'fs'}, 0x1003


class Link(_Link, table=True):
    """A link between a location or a file and a record of another schema."""
    __tablename__, __table_args__, __shard__ = 'links', {'schema': 'fs'}, 0x1010


app = api_at('/fs', 'fs', 'The file systems: their locations, files and what each source read of them.',
             operations('/fs/types', _Type, 'fs type', Type),
             operations('/fs/locations', _Record, 'location', Location),
             operations('/fs/files', _Record, 'file', File),
             operations('/fs/instances', _Record, 'instance', Instance),
             operations('/fs/links', _Link, 'fs link', Link))
