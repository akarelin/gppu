"""Linked Data's files API: the file systems Alex runs, as gppufs (gppu.fs) reads and configures them (_Projects/Linked Data,
"Linked Data - Universal types, statuses and sharding", # File system; "Linked Data - gppufs"). Separate from the core and built on
it (gppu.ld), beside gppufs; served at /ld/v1/files, documented at /ld/v1/files/docs.

Linked Data holds what gppufs is configured with and where its indexes are; the files are in gppufs's indexes, not in records. The
file system is 0x20-0x2F: an FS node is the base of every file system type, an FS location a place files are reached, an FS file
one file as a single thing wherever its copies are, an FS index a pointer to one gppufs index. Each is created, read, updated and
searched at `/files`; gppufs makes its catalog from the locations (gppu.ld.gppufs). Credentials are not stored: a Provider reads them where it declares them."""
from . import Type, _Record, api_at, typed


class FSNode(_Record, table=True):
    """The base of every file system type. Path: `/files`, with the others."""
    __tablename__ = 'fs_node'


class FSLocation(_Record, table=True):
    """A place files are reached: a connection and a path, gppufs's `Location`. A root location is its connection and its Provider,
    its connection's parameters in `data.handler`, and has no parent; every other location is inside the location above it.
    `data.uid` is its gppufs uid, `data.canonical` its canonical uri, and the rest of `data` its configuration as gppufs has it.
    `subtype`: `logical` or `physical`."""
    __tablename__ = 'fs_location'
    PARENTS = (Type.FS_LOCATION,)


class FSFile(_Record, table=True):
    """One file as a single thing, wherever its copies are: a collection. The copies are in gppufs's indexes; the FS file is what
    other records refer to."""
    __tablename__ = 'fs_file'


class FSIndex(_Record, table=True):
    """A pointer to one gppufs index: the SQLite file beside a location, or inside an archive, holding what a walk read of every
    file there."""
    __tablename__ = 'fs_index'


app = api_at('/files', 'files', 'The file systems as gppufs reads and configures them: their locations, files and indexes.',
             typed('/files', _Record, 'file', FSNode, FSLocation, FSFile, FSIndex))
