<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/fs.py 0863a0e39d1539a1a5dd876b4344762be65a53a4 -->
`gppu.fs` (gppufs) gives programs one way to read and write objects in the places they are kept: files on this host, files on a share, a Postgres database, or a SharePoint or OneDrive drive. A caller names an object by its uri or by a path relative to a place, and the module handles the connection, identity and what is remembered about each object.

## How the parts fit

A Location is one place in the configured hierarchy, known by its uid. It holds the Provider that reaches its objects, and `Location.container(path)` returns a Container at a path below it. `GppuCatalog` loads the configured Locations, returns one by uid with `location(uid)`, and finds the Location holding a uri with `location_of(uri)`.

A Provider reaches objects by uri over one connection. It implements `ls`, `info`, `open`, `read`, `write`, `delete` and `refresh` for its scheme. A base method left unimplemented raises `NotImplementedError`, and a write or delete the Provider does not allow raises `PermissionError`. `FileSystem` is the Provider of files: its `read` returns a JSON file's parsed value and any other file's byte stream.

A Container holds alike objects under one uri and takes only relative paths, so its callers never handle uris. Its `write` obeys the `.merge.yaml` rules in each folder, which decide whether a changed file may be replaced or a removed object deleted. Naming templates place a `DataObject` through `path_of`, and an identity template refuses to overwrite one object with another.

A `DataObject` is a frozen value holding content, the uri it came from, an identity, a kind and a name.

`GppuFileSystem` is an fsspec file system over one location. It keeps a SQLite index beside each folder it lists, or in an object implementing `GppuIndex` when the caller supplies one. `ls` and `info` identify an entry from its listing without reading it. `refresh=True` parses the entry with its handler from `gppu.handlers`. Archives (zip, tar.gz and rar) are opened only when they are listed themselves. Ignored files are neither indexed nor listed. `PostgresFileSystem` and `SharePointFileSystem` are read-only file systems for their stores; `PostgresFileSystem` registers as `pg://`.

Public I/O methods decorated with `sync` return directly outside an event loop and are awaitable inside one. Their `*_sync` methods run on the calling thread. The Lake, which saves and retrieves objects by uri, is in `gppu.lake`, not in this module.

## Using it

The example is the one from the module's `PostgresFileSystem` docstring:

```python
from gppu.fs import GppuFileSystem

fs = GppuFileSystem('pg://pg.karel.in/files', dsn='postgresql://…')
for entry in fs.ls('', detail=True):
    print(entry['name'])
```

The `dsn` is the caller's connection string, because which databases exist and how to reach them is configuration rather than part of this module.
