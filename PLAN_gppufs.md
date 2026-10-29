# gppufs as an fsspec file system

A session-sized job: gppufs.py is reworked, and its tests, the catalog, the desktop and the session cleaner are moved to it. What gppufs must be is in [SPEC_gppufs.md](SPEC_gppufs.md). `D:\_\_Standards\Systems\gppufs.md` and `Lake.md` are generated, not specification; the Linked Data standard's `byAlex` files are canonical for Linked Data.

## Deviations from fsspec today
- The constructor takes one folder and every path is read below it; fsspec gives one file system every path. Removed.
- `gppu` is not registered, so `fsspec.filesystem('gppu')` and `gppu::` addresses fail. Removed.
- `cachable = False`: fsspec reuses an instance for the same options. Removed.
- `locations=` and `index=`: gppufs knows locations and a database index. Moved to the catalog, as its own step.
- Rows are named by URI (`file://D:/...`); fsspec names entries by path. Removed with full paths.
- `refresh=True` re-reads what is not read as it is now, with the handlers: fsspec's meaning applied to what gppufs caches. Settled by the agent.
- With a catalog, gppufs lists and opens what its wrapped store does not hold: `catalog://` paths and any other store's address go to the catalog. Alex's instruction.
- `ls_sync`, `info_sync`, `ls_iter`, `move_into` and the `@sync` decorator: names and an async scheme fsspec does not have (`ls`, `info`, `_walk`, `mv`, `AsyncFileSystem`). Removed: gppufs and the catalog are fsspec `AsyncFileSystem`s; inside an event loop a caller awaits `_ls` and `_info`.
- `ls(path, recurse=True)` is gppufs's own recursion: an ignored folder listed and not entered, an archive whose listing is held entered. fsspec's `walk`, `find`, `copy -r` and `rm -r` keep fsspec's meaning.

## Tasks
- gppufs is `ChainedFileSystem` registered as `gppu`, takes full paths, finds the index from each path: done; the session cleaner's dry run lists both folders on it
- catalog, desktop, Lake, TUI and session cleaner on full paths: done, their tests pass
- one gppufs in a process; `cache` names the folders whose index stays in the cache: done
- locations and the database index out of gppufs; the location map in the catalog (`locate`, `resolve`): done
- the session cleaner in gppu's TUI: done
- gppufs's own tests on full paths: done, the whole suite passes
- refresh: never follows a junction, reads below once on a recursive refresh: done
- refresh of a folder of millions: read a folder at a time, written in batches of 1,000 rows: done
- catalog() reads location records as Linked Data - FS has them; a location is on this host by its handler's access, or below the location above it: done
- gppu.ld to the Linked Data standard as it is now (two-byte ids, shard1 the schema and shard2 the table, from `Linked Data.md`, the one `byAlex` file; the SQL and Python blocks of the LD, FS and Sessions notes, which are generated): done, its tests pass on Postgres

## Users of gppufs, moved in parallel (docs/gppufs-users.md)
- Lake service and Dagster (RAN `Systems/lake`, stacks `lake` and `dagster` on trix): done; both code locations build, 118 tests pass
- Linked Data service (RAN `Systems/ld`, stack `linked-data` on five), session hook and Session Manager: done, its sessions on gppu.ld.sessions and its checks on `/fs` pass on a scratch database; a session's messages read in their file's order: done; its core check and its pages (stack linked-data's `admin`) and `structure.py` (knowledge, a node type) on the new records: in progress; Session Manager's plain links are type `link`; serving waits on the gppu release and the standard's SQL on its database
- FileIndexer (RAN `Systems/ld/fileindexer`): done, posting locations as Linked Data - FS has them; 4 of 5 tests pass on a scratch database, the TUI test waits on WSL's network
- Admin UI and its APIs (CRAP `Systems/admin_ui`; RAN `Services/admin-ui`, `Services/admin-priors`): done; its configuration routes answer as the live API does, its tests pass as the running image's do, its docs page renders; its Linked Data record pages on the new API: in progress, the work, project and knowledge pages wait for `/work`'s schema
- Host tools (RAN `Hosts/preservator`, `Hosts/tui` session scripts): done, preservator saving through the Lake, `platform_for_os` restored
- Releases and deploys of the stacks: a gppu release from ld-standard, Alex's
- with a catalog, gppufs lists and opens through it what it holds no index for, SharePoint and archives among them: done; the catalog's address is the `catalog` option, from fsspec's configuration (`FSSPEC_GPPU_CATALOG`), none by default; bytes come from the Lake at the entry's address
- each index row carries its file's UUID (`uuid_create(0x10, 0x02)`, fs.files as Linked Data - FS has it), kept through a refresh, a change and a move: done; an index on a store this host does not own holds its ids in memory until its own host writes it; finding a file by its UUID: not started
- gppufs on fsspec's `AsyncFileSystem`, its callers moved: done in gppu and RAN, the suite passes, the session cleaner's dry run finds the same sessions; the admin API's inventory readers: in progress
- the catalog's Location binds this host's folder for a location reached through `handler.access`, not the canonical's: done
- the Lake keeps its index at its root, never in its day folders: done, as the Lake on s1 already has it

## In progress: full paths
- `_key` normalizes a full path; `_path` is identity; `root` and `location` go.
- A row is named by its path, as fsspec names entries; no URI is built per row.
- `_owner` walks the path's folders up to the store's root; the deepest index there owns the entry.
- No index at or above: the index goes beside the folder listed, a file's beside its folder.
- `cache=False` keeps every owner's index in the cache, by the same rule.

/goal gppufs is `fsspec.filesystem('gppu')` and `gppu::<url>` with full paths and the index found from each path; proven by the gppufs tests passing and the session cleaner's dry run listing both folders in seconds; RAN and CRAP untouched.

## Found, not this task
- The Lake API has no batch route: preservator makes two calls per file on every run, files already preserved included.
- FileIndexer could write files to Linked Data with `PUT /fs/files/{gppu.id}`; it writes none today.
- WSL has no network, so FileIndexer's TUI test cannot run there; Windows does not reach the scratch database.
- gppu has no public field for the first line a person typed; the session tools read it from `normalized_name`.
- RAN `Systems/lake/plaud/test_dagster_incremental.py` calls `download_recordings` with the signature CRAP d1091211 (2026-09-24) replaced.
- RAN `Systems/lake/m365/locations/karelin.py` and `tulaco.py` need a `lake.yaml` that is not in the repository; their compose services are commented out.
- RAN `Systems/lake/tests/test_age.py`, `test_catalog_graph.py` and `test_graph_read.py` run inside a transaction on pg.karel.in/everything; not run.
