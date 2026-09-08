---
fileClass: Document
created: 2026-09-05
updated: 2026-09-06
generated: { by: Codex/GPT-6, at: '2026-09-06 03:33 -07:00' }
---

The examples construct `GppuCatalog` and use only `ls` and `info`. `handler_ls.py` prints complete JSON metadata; `handler_browser.py` displays one tree of Locations, folders, archives and files with the highlighted entry's complete metadata. `handler_tui.py` launches the same browser. Parsing, aggregates, SQLite storage, shard routing, and external rename recovery belong to `gppu.handlers`.

Both examples load `examples/handlers.yaml` through `Env`:

```yaml
catalog: D:\TextLake\.catalog
```

`catalog` is the only setting: an absolute folder with one subfolder per host or server, named as the Locations table names it, holding that host's `locations.yaml`: one row per Location as the table has it, plus `root_path`, the absolute path of the Location on that host, and `index`, where gppufs keeps that Location's index. gppufs opens the folder named after the machine it runs on. The YAML files beside the host folders are the global catalog, one per service, the file name being the service: `sharepoint.yaml`, `synology-drive.yaml`, `google-drive.yaml`, `dropbox.yaml`, `obsidian.yaml`, `git.yaml`. Each holds that service's canonical `locations`, nested, a location carrying its children in its own `locations`, servers at the top: `s1` over the Synology Drive shares, each with `sd` and `smb` paths and a hand-written `history`; `m365-karelin` over its SharePoint libraries with `origin`, `site` and `library`, the personal OneDrive among them; `github` over the repositories with their `url`; `dropbox` over its shared folders. Physical copies stay separate: a host folder's `replicas.yaml` says, per service, where that host holds a copy of a location, named by its path of names in that tree, with the local path and `checked_at`, the last time the folder was seen there. A folder that is a replica carries a `source` block with the service, the location's path of names, its server, what the catalog says of it, and `checked_at`, so `D:\Karelin` is a replica of `sharepoint m365-karelin` and `D:\OneDrive - Karelin\Finance` of `sharepoint m365-karelin/Finance`. The block shows as the Source column. A replica of a location the service file does not list is refused. gppufs derives the same index path from the Location and refuses a row that says otherwise, so the catalog cannot move an index. The examples start at the catalog: its root lists the Locations without touching them, entering one lists that Location, and Backspace walks up the Locations tree back to the catalog. A `GppuFileSystem` can still be built on one Location directly.

With the repository virtual environment active, `python examples/handler_ls.py` prints the catalog's Locations; with a Location path as its argument it prints that Location and everything below it. `python examples/handler_browser.py` opens the TUI: the catalog's Locations as a tree, Locations in bold, before any folder is read. Enter or Right expands a Location, folder or archive and lists it; Left collapses, or moves to the parent; highlighting a row shows its `info`, which probes a file once; `r` refreshes the highlighted row from the source, its whole listing when it is a container; `f` hides or shows files and `i` ignored entries, so the tree can be folders only; `q` exits. The Indexed column is the row's last refresh. The catalog row carries the totals and the latest refresh its Locations' indexes hold, and each Location row what its own index holds, without reading any folder. The TUI awaits `gppufs.ls` and `gppufs.info`, whose reading runs off the event loop, and displays failures. It has no rename action.

```python
from gppu.handlers import GppuFileSystem

gppufs = GppuFileSystem(location=r'D:\Downloads')
root = gppufs.info()
children = gppufs.ls()
descendants = gppufs.ls(recurse=True)
fresh_children = gppufs.ls(refresh=True)
```

Inside a running event loop the same calls are awaited: `await gppufs.ls()`. The reading runs in a worker thread either way.

`ls` reads the folder live. Every entry it has not seen is identified: native attributes, the handlers that match, and for a file its byte count and name span. Nothing is parsed. A folder's file, folder and byte totals and span are null until that folder is refreshed, and `gppu.probed` is false. `ls(refresh=True)` probes the folder and everything below it; `info(file)` probes that one file the first time its details are asked for. Entries already in the index keep their indexed metadata until a refresh. An entry that is gone from the folder is dropped from the listing; its row is removed by the next refresh of that folder. Entering an archive lists its members the same way: identified from their names and bytes, none probed, folder totals null. A member is probed when its details are asked for; refreshing the archive probes all of them.

`ls` follows fsspec's detailed-listing shape: a list of dictionaries. `detail=False` returns names. `info` returns one dictionary, with the same metadata as its listing entry. Names are addressable URIs. ZIP and TAR.GZ members use fsspec chained URLs; RAR uses a registered `gppu-rar` archive adapter over the existing `ArchiveHandler` and installed RARLAB command. Recursion also descends into supported archives.

| Returned property | Presence | Source |
| --- | --- | --- |
| `name`, `type`, `size` | Required | Native fsspec entry; `name` is the addressable URI, `type` is `file` or `directory`. |
| Other native fields | Backend dependent | fsspec attributes, such as `mtime`, `created`, `ino`, or archive header fields. |
| `gppu` | Required | Handler metadata described below. |

| `gppu` property | Presence | Source |
| --- | --- | --- |
| `path`, `name`, `parent` | Required; `parent` is null at the location root | Current URI, display filename, and navigable parent URI. |
| `type`, `size`, `modified_at`, `handlers` | Required; `modified_at` can be null | Existing `Record` properties; `type` is `file` or `folder`. Every time, here and in spans, is in the host's local zone. |
| `files`, `folders`, `bytes`, `span` | Required; null for a folder that has not been probed, `span` can be null | Existing hierarchy statistics. Physical archives count as files in their containing folder; their member listings have their own aggregates. |
| `probed`, `probed_at` | Required; `probed_at` null until the entry is probed | Whether the entry has been probed and, in the host's local zone, when it last was. A catalog Location row carries its index root's values; the catalog row the latest of them. |
| `probed` | Required boolean | False for an entry the listing identified but nothing has parsed yet. |
| `stats` | Required mapping | Each matched handler's statistics, keyed by handler name. Empty until probed. |
| Named handler metadata, e.g. `markdown`, `session`, `git` | When supplied by that handler | All parsed metadata. Markdown frontmatter stays verbatim in `gppu.markdown`; session metadata includes identity, topic, models, span, and turn count. |
| `is_container` | Required boolean | Folder or supported archive, subject to ignored/no-descent rules. |
| `errors` | Only on parser errors | Existing handler, operation, error type, and message. |

Both live and cached results pass through the same JSON representation: dates and datetimes are strings, sequences are lists, and absent known values remain null. Handler statistics are stored separately from parsed metadata so a frontmatter field called `stats` is preserved.

The first read of a folder identifies it and its entries and stores that. Probing fills the metadata: `refresh=True` on a folder, or a file's first `info`. `refresh=True` rereads source metadata and replaces the requested subtree, including additions and removals, even when file sizes and timestamps have not changed. Cached ancestors receive updated file, folder, byte, and span aggregates using the refreshed subtree and cached siblings. Other indexed subtrees remain cached snapshots. Index files and SQLite journal companions are excluded from listings and aggregate sizes.

The location is an absolute path or a URL; a relative location is refused, so the folder an example is started in never becomes one. The database is `{location}/.{location-name}.gppufs.sqlite`, created at the first listing and nowhere else. An existing `{location}/folder/.{folder-name}.gppufs.sqlite` is a shard: it owns that folder's subtree, at any depth, and the deepest enclosing shard owns an entry. The parent index retains the child listing reference. `gppu.data` is not involved.

| SQLite table | Columns | Meaning |
| --- | --- | --- |
| `gppufs_entries` | `path TEXT PRIMARY KEY`, `metadata TEXT NOT NULL`, `children TEXT` | Index-relative address, complete JSON metadata, and direct child references. `children` is null for files. |
| `gppufs_index` | `ino INTEGER` | Native folder identity, including when the first request indexed only a file. Null when the backend has no inode. |

Cached entry paths and handler-owned source paths are plain relative paths. When a containing folder is renamed externally, browsing its new location discovers and renames the carried SQLite file; its rows are reused. For a renamed descendant folder, native inode identity lets gppufs update references in the parent index and retain the subtree's metadata. User frontmatter and transcript-derived text are not rewritten. This also works when the folder has no shard and all its rows are in an ancestor index. A relocated location root is opened using its new URI.

Descendant rename reconciliation requires stable folder identity from the backend. A backend without inode identity can recover a uniquely identifiable carried index at the new location, but cannot infer an unsharded descendant rename from names alone. SQLite write failures and ambiguous index identity are surfaced; index storage is never redirected elsewhere.
