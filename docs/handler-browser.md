---
fileClass: Document
created: 2026-09-05
updated: 2026-09-06
generated: { by: Codex/GPT-6, at: '2026-09-06 03:33 -07:00' }
---

The examples construct `GppuFileSystem` and use only `ls` and `info`. `handler_ls.py` prints complete JSON metadata; `handler_browser.py` displays a directory table and the selected entry's complete metadata. `handler_tui.py` launches the same browser. Parsing, aggregates, SQLite storage, shard routing, and external rename recovery belong to `gppu.handlers`.

Both examples load `examples/handlers.yaml` through `Env`:

```yaml
location: .
```

`location` is the only required setting: a directory path or fsspec URI. `.` means the process's current directory. Index paths are derived from the location and folder names. The config has no index storage override.

With the repository virtual environment active, `python examples/handler_ls.py` prints the recursive listing and `python -m examples.handler_browser` opens the TUI. Enter opens a folder or archive; Backspace returns to its parent within the configured location; `r` refreshes the current listing from the source; `q` exits. The TUI performs filesystem calls in background threads and displays failures. It has no rename action.

```python
from gppu.handlers import GppuFileSystem

gppufs = GppuFileSystem(location='.')
root = gppufs.info()
children = gppufs.ls()
descendants = gppufs.ls(recurse=True)
fresh_children = gppufs.ls(refresh=True)
```

`ls` follows fsspec's detailed-listing shape: a list of dictionaries. `detail=False` returns names. `info` returns one dictionary, with the same metadata as its listing entry. Names are addressable URIs. ZIP and TAR.GZ members use fsspec chained URLs; RAR uses a registered `gppu-rar` archive adapter over the existing `ArchiveHandler` and installed RARLAB command. Recursion also descends into supported archives.

| Returned property | Presence | Source |
| --- | --- | --- |
| `name`, `type`, `size` | Required | Native fsspec entry; `name` is the addressable URI, `type` is `file` or `directory`. |
| Other native fields | Backend dependent | fsspec attributes, such as `mtime`, `created`, `ino`, or archive header fields. |
| `gppu` | Required | Handler metadata described below. |

| `gppu` property | Presence | Source |
| --- | --- | --- |
| `path`, `name`, `parent` | Required; `parent` is null at the location root | Current URI, display filename, and navigable parent URI. |
| `type`, `size`, `modified_at`, `handlers` | Required; `modified_at` can be null | Existing `Record` properties; `type` is `file` or `folder`. |
| `files`, `folders`, `bytes`, `span` | Required; `span` can be null | Existing hierarchy statistics. Physical archives count as files in their containing folder; their member listings have their own aggregates. |
| `stats` | Required mapping | Each matched handler's statistics, keyed by handler name. |
| Named handler metadata, e.g. `markdown`, `session`, `git` | When supplied by that handler | All parsed metadata. Markdown frontmatter stays verbatim in `gppu.markdown`; session metadata includes identity, topic, models, span, and turn count. |
| `is_container` | Required boolean | Folder or supported archive, subject to ignored/no-descent rules. |
| `errors` | Only on parser errors | Existing handler, operation, error type, and message. |

Both live and cached results pass through the same JSON representation: dates and datetimes are strings, sequences are lists, and absent known values remain null. Handler statistics are stored separately from parsed metadata so a frontmatter field called `stats` is preserved.

The first uncached read parses the requested hierarchy and stores its metadata. Later reads reuse the index. `refresh=True` rereads source metadata and replaces the requested subtree, including additions and removals, even when file sizes and timestamps have not changed. Cached ancestors receive updated file, folder, byte, and span aggregates using the refreshed subtree and cached siblings. Other indexed subtrees remain cached snapshots. Index files and SQLite journal companions are excluded from listings and aggregate sizes.

The default database is `{location}/.{location-name}.gppufs.sqlite`. An existing `{location}/folder/.{folder-name}.gppufs.sqlite` owns that folder's subtree. A folder can become a shard by browsing it as the location of another `GppuFileSystem` instance. Shards can occur at any depth, and the deepest enclosing shard owns an entry. The parent index retains the child listing reference. `gppu.data` is not involved.

| SQLite table | Columns | Meaning |
| --- | --- | --- |
| `gppufs_entries` | `path TEXT PRIMARY KEY`, `metadata TEXT NOT NULL`, `children TEXT` | Index-relative address, complete JSON metadata, and direct child references. `children` is null for files. |
| `gppufs_index` | `ino INTEGER` | Native folder identity, including when the first request indexed only a file. Null when the backend has no inode. |

Cached entry paths and handler-owned source paths are plain relative paths. When a containing folder is renamed externally, browsing its new location discovers and renames the carried SQLite file; its rows are reused. For a renamed descendant folder, native inode identity lets gppufs update references in the parent index and retain the subtree's metadata. User frontmatter and transcript-derived text are not rewritten. This also works when the folder has no shard and all its rows are in an ancestor index. A relocated location root is opened using its new URI.

Descendant rename reconciliation requires stable folder identity from the backend. A backend without inode identity can recover a uniquely identifiable carried index at the new location, but cannot infer an unsharded descendant rename from names alone. SQLite write failures and ambiguous index identity are surfaced; index storage is never redirected elsewhere.
