# gppufs as an fsspec file system

A session-sized job: gppufs.py is reworked, and its tests, the catalog, the desktop and the session cleaner are moved to it. What gppufs must be is in [SPEC_gppufs.md](SPEC_gppufs.md). `D:\_\_Standards\Systems\gppufs.md` and `Lake.md` are generated, not specification; the Linked Data standard's `byAlex` files are canonical for Linked Data.

## Deviations from fsspec today
- The constructor takes one folder and every path is read below it; fsspec gives one file system every path. Removed.
- `gppu` is not registered, so `fsspec.filesystem('gppu')` and `gppu::` addresses fail. Removed.
- `cachable = False`: fsspec reuses an instance for the same options. Removed.
- `locations=` and `index=`: gppufs knows locations and a database index. Moved to the catalog, as its own step.
- Rows are named by URI (`file://D:/...`); fsspec names entries by path. Removed with full paths.
- `refresh=True` re-reads what is not read as it is now, with the handlers: fsspec's meaning applied to what gppufs caches. Settled by the agent.
- `ls_sync`, `info_sync`, `ls_iter`, `move_into` and the `@sync` decorator: names and an async scheme fsspec does not have (`ls`, `info`, `_walk`, `mv`, `AsyncFileSystem`). Replaced by fsspec's in the async step.

## Tasks
- gppufs is `ChainedFileSystem` registered as `gppu`, takes full paths, finds the index from each path: done; the session cleaner's dry run lists both folders on it
- catalog, desktop, Lake, TUI and session cleaner on full paths: done, their tests pass
- one gppufs in a process; `cache` names the folders whose index stays in the cache: done
- locations and the database index out of gppufs; the location map in the catalog (`locate`, `resolve`): done
- the session cleaner in gppu's TUI: done
- gppufs's own tests on full paths: in progress
- refresh: never follows a junction, reads below once on a recursive refresh: done
- refresh of a folder of millions: read and written in batches, not held whole in memory: next
- gppu.ld to the Linked Data standard as it is now (`byAlex` files: two-byte ids, shard1 the schema and shard2 the table; LD, FS and Sessions SQL and Python blocks): next; no other session works on it

## Users of gppufs, moved in parallel (docs/gppufs-users.md)
- Lake service and Dagster (RAN `Systems/lake`, stacks `lake` and `dagster` on trix): in progress
- Linked Data service (RAN `Systems/ld`, stack `linked-data` on five): in progress
- FileIndexer (RAN `Systems/ld/fileindexer`; CRAP `Projects/FileIndexer`): in progress
- Admin UI and its APIs (CRAP `Systems/admin_ui`; RAN `Services/admin-ui`, `Services/admin-priors`): in progress
- Host tools (RAN `Hosts/preservator`, `Hosts/tui` session scripts): in progress
- Releases and deploys of the stacks: a gppu release from ld-standard, Alex's
- each index row carries its file's UUID (`uuid_create`, the file shard as Linked Data's code has it, 0x13); code finds files by UUID, not URI: not started
- gppufs on fsspec's `AsyncFileSystem`: not started

## In progress: full paths
- `_key` normalizes a full path; `_path` is identity; `root` and `location` go.
- A row is named by its path, as fsspec names entries; no URI is built per row.
- `_owner` walks the path's folders up to the store's root; the deepest index there owns the entry.
- No index at or above: the index goes beside the folder listed, a file's beside its folder.
- `cache=False` keeps every owner's index in the cache, by the same rule.

/goal gppufs is `fsspec.filesystem('gppu')` and `gppu::<url>` with full paths and the index found from each path; proven by the gppufs tests passing and the session cleaner's dry run listing both folders in seconds; RAN and CRAP untouched.
