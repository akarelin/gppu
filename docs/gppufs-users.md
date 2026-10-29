# Moving a user of gppufs to the new gppufs

This is what changed in gppu on the `ld-standard` branch, and how code that uses it moves over. The design is in the gppufs standard, section The file system (`D:\_\_Standards\Systems\gppufs.md`). Open decisions are in [gppufs-decisions.md](gppufs-decisions.md).

## gppufs
- **One gppufs in a process.** `GppuFileSystem()`, `fsspec.filesystem('gppu')` and `gppu::D:/TextLake` all give the same object, which wraps this host's files. `gppu::smb://...` or `GppuFileSystem(target_protocol=..., target_options=...)` wraps another store. Nothing makes a second one. Constructing it again with different options raises an error.
- **Full paths.** Every call takes the full path as the wrapped file system names it: `fs.ls('D:/TextLake/notes')`, `fs.info('C:/Users/Alex/.codex/sessions/x.jsonl')`. There's no root, and no `ls()` or `info()` without a path.
- **Rows are named by path.** A row's `name` and `gppu.path` are its full path, and `gppu.parent` is its parent's path, or None at a store root. URIs are no longer built for every row.
- **The index is found from the path:** the deepest folder at or above it that holds `.<folder>.gppufs.sqlite`. With none above, a listing makes the index beside the folder listed, or beside a file's folder.
- **`cache=[folders]`** replaces `cache=False`. It names the folders whose index is kept in the cache instead of beside them, such as a folder another program watches or a synced folder. Set it on the first construction, or through fsspec's configuration for `gppu`.
- **Gone:** `fs.root`, `fs.location`, the `locations=` and `index=` options, the `GppuIndex` hook, and `move_into` (use `fs.makedirs(parent, exist_ok=True)`, then `fs.mv(source, destination, recursive=True)`).
- **gppufs's own operations, all with full paths:** `stored(path)`, `stats(path, apart=[folders])`, `spans(path, depth)`, `split(path)` (give a folder its own index), `preserve(path, folder)`, `ls_iter(path)`.
- **Use fsspec's methods** (`ls`, `info`, `find`, `walk`, `exists`, `open`, `cat_file`, `mv`, `makedirs`), not `ls_sync` or `info_sync`. Those two will go when gppufs moves onto fsspec's async base.

## Locations: the catalog, `gppu.fs.catalog`
- **`GppuCatalog(rows, ...)`** takes the location and connection rows its user loaded. It no longer reads gppu's configuration by itself; to use that configuration, pass `Env.glob_dict('')`.
- **`catalog(records, **location_types)`** builds the catalog from Linked Data's location records, the items of `GET /fs/locations`, which the caller fetches itself. `connect()` and `ld()` are no longer in gppu.
- **`Catalog(dsn, records)`** is the Lake catalog's Postgres reader, behind `/lake/catalog`. `records` is a callable that returns Linked Data's location records.
- **The location map gppufs used to hold:** `folders = reached(catalog)` gives the folders on this host and their locations. `locate(folders, row)` adds `gppu.location` (location, canonical, address, folder) and the `location` handler to a row. `resolve(folders, address)` turns `sd://SD.agents/...` into the path on this host. For a location's totals without the locations below it, use `stats(path, apart=[their folders])`.
- **Gone:** `filesystem(catalog, uid, folders)` and `GppuCatalog.filesystem(uid)`. Use `here(catalog, canonical)` for the folder and the one gppufs for the listing.
- **Host-folder catalogs** (`GppuCatalog('D:/TextLake/.catalog')`) work as before, on the one gppufs. Each location gets its own index the first time it's reached.

## The Lake, `gppu.fs.lake`
- `Lake(catalog, store, templates)` is unchanged for its callers. It names rows by its own URIs and lists through the one gppufs.

## Desktop and TUI
- `DesktopFileSystem({name: 'gppu::D:/TextLake', 'Catalog': CatalogFileSystem(url)})` takes gppufs addresses, or a file system served by an API.
- `HandlerBrowser(fs, root)` takes the folder it browses.
- A launcher manifest's `inline: true` modes run in the background, and the launcher shows their output in color.

## Tests
- `tests/conftest.py` clears the one gppufs before each test: `GppuFileSystem.clear_instance_cache()` and `gppu.fs.gppufs._INDEXES.clear()`.
