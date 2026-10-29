# gppufs as an fsspec file system

A session-sized job: gppufs.py is reworked, and its tests, the catalog, the desktop and the session cleaner are moved to it. What gppufs must be is in the gppufs standard, section The file system (`D:\_\_Standards\Systems\gppufs.md`); the rest of that standard is untrusted, and so is the Lake's.

## Deviations from fsspec today
- The constructor takes one folder and every path is read below it; fsspec gives one file system every path. Removed.
- `gppu` is not registered, so `fsspec.filesystem('gppu')` and `gppu::` addresses fail. Removed.
- `cachable = False`: fsspec reuses an instance for the same options. Removed.
- `locations=` and `index=`: gppufs knows locations and a database index. Moved to the catalog, as its own step.
- Rows are named by URI (`file://D:/...`); fsspec names entries by path. Removed with full paths.
- `refresh=True` runs the handlers; fsspec's `refresh` reads the store again. Kept until Alex decides.
- `ls_sync`, `info_sync`, `ls_iter`, `move_into` and the `@sync` decorator: names and an async scheme fsspec does not have (`ls`, `info`, `_walk`, `mv`, `AsyncFileSystem`). Replaced by fsspec's in the async step.

## Tasks
- gppufs is `ChainedFileSystem` registered as `gppu`, takes full paths, finds the index from each path: done; the session cleaner's dry run lists both folders on it
- catalog, desktop, Lake, TUI and session cleaner on full paths: done, their tests pass
- gppufs's own tests on full paths: in progress
- `locations=` and `index=` out of gppufs into the catalog: not started
- each index row carries its file's UUID (`uuid_create`, the file shard as Linked Data's code has it, 0x13); code finds files by UUID, not URI: not started
- gppufs on fsspec's `AsyncFileSystem`: not started

## In progress: full paths
- `_key` normalizes a full path; `_path` is identity; `root` and `location` go.
- A row is named by its path, as fsspec names entries; no URI is built per row.
- `_owner` walks the path's folders up to the store's root; the deepest index there owns the entry.
- No index at or above: the index goes beside the folder listed, a file's beside its folder.
- `cache=False` keeps every owner's index in the cache, by the same rule.

/goal gppufs is `fsspec.filesystem('gppu')` and `gppu::<url>` with full paths and the index found from each path; proven by the gppufs tests passing and the session cleaner's dry run listing both folders in seconds; RAN and CRAP untouched.
