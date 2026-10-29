# Moving a user of gppufs to the new gppufs

This is what changed in gppu on the `ld-standard` branch, and how code that uses it moves over. Alex's instructions are in [SPEC_gppufs.md](../SPEC_gppufs.md). His rulings with their sources are in [gppufs-decisions.md](gppufs-decisions.md).

## gppufs
- **One gppufs in a process.** `GppuFileSystem()`, `fsspec.filesystem('gppu')` and `gppu::D:/TextLake` all give the same object, which wraps this host's files. `gppu::smb://...` or `GppuFileSystem(target_protocol=..., target_options=...)` wraps another store. Nothing makes a second one.
- **Full paths.** Every call takes the full path as the wrapped file system names it: `fs.ls('D:/TextLake/notes')`, `fs.info('C:/Users/Alex/.codex/sessions/x.jsonl')`. There's no root, and no `ls()` or `info()` without a path.
- **Rows are named by path.** A row's `name` and `gppu.path` are its full path, and `gppu.parent` is its parent's path, or None at a store root. URIs are no longer built for every row.
- **The index is found from the path:** the deepest folder at or above it that holds `.<folder>.gppufs.sqlite`. With none above, a listing makes the index beside the folder listed, or beside a file's folder.
- **`cache=[folders]`** replaces `cache=False`. It names the folders whose index is kept in the cache instead of beside them, such as a folder another program watches or a synced folder. The one gppufs keeps every folder any of its users names.
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

## Removed from gppu before this rework
- **`State`** and its tables (`Env.locations`, `Env.connections`, `Env.<table>.<rule>`) are gone (f6d80a7). Configuration is in Env (`glob`, `Env.glob_dict`, `self.my`). Locations and connections are `GppuCatalog(rows)`. Other tables and their rules, the `dsn` macro among them, are rendered by `TemplateSet` from the configuration.
- **`SessionFile`, `SessionFolder`, `HandlerError`, `_MetadataHandlers` and the callable `SessionHandler()`** are gone (f749092). A session is read by `SessionHandler.parse(path)`. Its message objects come from `SessionHandler.lines(path)`, its turns from `SessionHandler.turns(lines)` and its models from `SessionHandler.models(lines)`. What a person typed comes from `SessionHandler.human_messages(turns)`. Linked Data's session messages come from `SessionHandler.parse_messages(harness, lines)`. A path's handler comes from `handlers.probe(path)` and `handlers.HANDLERS`.
- **`CliApp`** is archived (c0a3e12). A program sets `APP['cli'] = True`, or is an `App` with `Env.from_argv` laid over its configuration.
- **`init_logger`** is the environment's (`Env.init_logger`), and the program's log is `Logger` (9bb507d). **`is_table_key`** is gone (cba50f0).
