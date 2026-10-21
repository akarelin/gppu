<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/fs.py 7300ea3361d9ed9286e6922ee7eee30839f1abac -->
`gppu.fs` (gppufs) reads objects from the places where they are kept, and it indexes the files among them. An object is content with the uri it came from. A file system for a folder tree keeps what it learned of each entry in a SQLite index beside that folder. The public methods are the API. The Lake, which saves objects and retrieves them by uri, is in `gppu.lake`.

A Location is one place in the configured hierarchy, known by its uid. Each Location has a Provider, which reaches objects by uri over one connection. An instance of a Provider is that connection. `FileSystem` is the Provider for files on this host or on a share it reaches. A Provider that cannot write raises `PermissionError` from `write` and `delete`. `PostgresFileSystem` and `SharePointFileSystem` are read-only fsspec file systems for a Postgres database and a SharePoint or OneDrive drive. A Container, obtained with `Location.container(path)`, holds alike objects and takes paths relative to itself. It adds naming templates, which decide where a `DataObject` is stored, and `.merge.yaml` rules, which decide what a write may replace. A `DataObject` carries the uri, content, identity, kind and name of one object, and a `removed` flag that a refresh sets when the source reports the object gone.

`GppuCatalog` loads the configured connections and Locations. `location(uid)` returns a Location with the Provider of its connection, and `location_of(uri)` finds the nearest configured Location at or above a uri. Given a folder of exported host catalogs, it answers every address with the `GppuFileSystem` of the deepest Location that contains it.

`GppuFileSystem` is the fsspec file system of one location, given as an absolute path or a URL. `ls` and `info` identify each entry from its listing by probe and read nothing. With `refresh=True` they parse the entry with its handler, and the row carries that handler's record under `gppu.record`. A `GppuIndex` passed to the file system is asked first, so an entry it already holds is not parsed again. An archive is opened only when it is listed itself. Writes through the fsspec surface change the file and leave the index as it was, until the folder is read with `refresh=True`.

`walk_files` walks a folder on this host, and `walk_container` walks any Container. Each yields every folder with the rows it holds, read to a level from `refresh` to `archives`.

Public I/O calls on `GppuFileSystem` and `GppuCatalog` return directly outside an event loop and are awaitable inside one. Their `*_sync` methods run on the calling thread.

## Using it

```python
from gppu.fs import GppuFileSystem

fs = GppuFileSystem('D:/Dev')                          # the location: an absolute path or a URL
names = fs.ls('', detail=False)                        # identified from the listing, nothing read
row = fs.info('README.md', refresh=True)               # parsed by its handler; row['gppu']['record'] holds the record
```
