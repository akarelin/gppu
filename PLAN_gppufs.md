# gppufs as an fsspec file system

A session-sized job: gppufs.py is reworked, and its tests, the catalog, the desktop and the session cleaner are moved to it. What gppufs must be is in [SPEC_gppufs.md](SPEC_gppufs.md). `D:\_\_Standards\Systems\gppufs.md` and `Lake.md` are generated, not specification; the Linked Data standard is `Linked Data.md`, the one note marked active; its LD, FS and Sessions notes are generated drafts, not specification.

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
- catalog() reads location records as gppu.ld.fs has them; a location is on this host by its handler's access, or below the location above it: done
- gppu.ld to the Linked Data standard as it is now (two-byte ids, shard1 the schema and shard2 the table, from `Linked Data.md`; its SQL and Python first copied from the LD, FS and Sessions notes, which are generated): done, its tests pass on Postgres
- gppu.ld checked against `Linked Data.md` alone: flags change only by its transitions, `delete` among them; a record's children listed by `records_list`; every schema's root types at the root of their schema, none under another schema's types; a link written as any record is, its ends and its type not checked, which were the agents' rules; code and SQL cite `Linked Data.md` and gppu.ld, not the generated notes; `type` stays text; ids, span, shard codes and slugs already matched: done, the gppu, FileIndexer and admin suites pass on the scratch database

## Users of gppufs, moved in parallel (docs/gppufs-users.md)
- Lake service and Dagster (RAN `Systems/lake`, stacks `lake` and `dagster` on trix): done; both code locations build, 118 tests pass
- Linked Data service (RAN `Systems/ld`, stack `linked-data` on five), session hook and Session Manager: done, its sessions on gppu.ld.sessions and its checks on `/fs` pass on a scratch database; a session's messages read in their file's order: done; its core check, its pages (stack linked-data's `admin`) and `structure.py` (knowledge, a node type) on the new records: done, the pages built and type-checked, their browser check waiting on WSL's network; Session Manager's plain links are type `link`; serving waits on the gppu release and gppu.ld's SQL on its database
- FileIndexer (RAN `Systems/ld/fileindexer`): done, posting locations as gppu.ld.fs has them; its tests pass on Windows against a scratch database
- Admin UI and its APIs (CRAP `Systems/admin_ui`; RAN `Services/admin-ui`, `Services/admin-priors`): done; its configuration routes answer as the live API does, its tests pass as the running image's do, its docs page renders; its Linked Data record pages on the new API: done, drawn in a browser against a scratch database; the work, project and knowledge pages wait for `/work`'s schema, Systems and Processes for the entity types they filter by
- gppu.ld: a sort by span, a type's update without its slug and shard, a link's type checked against the store's types, removed again as a rule Alex did not write: done, its tests pass on Postgres
- Host tools (RAN `Hosts/preservator`, `Hosts/tui` session scripts): done, preservator saving through the Lake, `platform_for_os` restored
- Releases and deploys of the stacks: a gppu release from master, Alex's
- with a catalog, gppufs lists and opens through it what it holds no index for, SharePoint and archives among them: done; the catalog's address is the `catalog` option, from fsspec's configuration (`FSSPEC_GPPU_CATALOG`), none by default; bytes come from the Lake at the entry's address
- each index row carries a UUID, made by gppufs (`uuid_create(0x1002)`), kept through a refresh, a change and a move: done; an index on a store this host does not own holds its ids in memory until its own host writes it; finding an entry by its UUID: not started
- the handler generates the UUID, an instance's or a file's by its target: not started; which handlers target which is in the gppufs note's "For Alex to decide"
- the gppufs and Lake notes in `Linked Data.md`'s style, conventions from the spec and the code, then their processes, life cycles and types as unverified details; the earlier text of each its Implementation note: done
- gppufs on fsspec's `AsyncFileSystem`, its callers moved: done in gppu and RAN, the suite passes, the session cleaner's dry run finds the same sessions; the admin API's inventory readers await `_ls` and `_info`: done
- the catalog's Location binds this host's folder for a location reached through `handler.access`, not the canonical's: done
- the Lake keeps its index at its root, never in its day folders: done, as the Lake on s1 already has it

## In progress: gppufs and gppu.ld on master
What matters is gppufs working, and its code merged so the new Linked Data, gppu.ld, works on top of it.
- `ld-standard` into master as a fast-forward, the whole suite passing on the scratch database: done; gppu's work goes to master.
- Every user of gppufs on master and pushed: done; vfs, the desktop, the handler browser, the session cleaner, the Lake and Dagster, the Linked Data service, the session hook, Session Manager, FileIndexer and its TUI, the admin UI and the host tools already ran on it, their tests passing; CRAP `Projects/FileIndexer`'s tests import `GppuCatalog` from `gppu.fs.catalog`; RAN `Systems/ld/ld.sql` is gppu.ld's SQL, and the Linked Data image installs every module gppu.ld needs from master
- RAN `.github/workflows/ld.yml` building from `Systems/ld`: committed in RAN, not pushed; its push was refused as a production deploy, and workflow code is Alex's
- No workflow runs on a push; a release and the deploys stay Alex's. RAN's Linked Data and Lake images install gppu from master, so their next build takes gppufs and gppu.ld, which need gppu.ld's SQL on `linked_data` first.

/goal gppufs and gppu.ld are on gppu's master and every user of gppufs is updated to it and pushed; proven by the gppu suite and each user's tests passing against the scratch database; no release, deploy or production write.

## Found, not this task
- `examples/handler_ls.py` and the handler browser's `main` stop: `D:\TextLake\.catalog`, the catalog `examples/handlers.yaml` names, has no folder for this host, which the host-folder catalog has required since 2026-09-08, the day the folder was last written.
- RAN `Projects/linkml/checks/test_current_standard.py` imports `gppu.fs.files`, now `gppu.ld.fs`, and fails on more than the import; another session is working in that folder.
- The admin API's image installs gppu from the `gppu/latest` tag; the Linked Data and Lake images install it from master.
- WSL's mirrored networking gives its VM no network device on this host; WSL runs in NAT mode, reaches Windows and is reached at localhost, and Windows does not forward its traffic further.
- The admin's Linked Data pages count records with one request per type, about 60 on a store made from gppu.ld's SQL.
- The Lake API has no batch route: preservator makes two calls per file on every run, files already preserved included.
- FileIndexer could write files to Linked Data with `PUT /fs/files/{gppu.id}`; it writes none today.
- gppu.ld has what `Linked Data.md` does not define, from the generated notes: the `ld.records` parent table, the columns `name`, `data`, `meta`, `created` and `updated`, and the API's routes.
- A record's status is not checked against its type's statuses.
- The Systems collector's runs were activities of subtype `collection`, which is the core's node type, so `POST /records` cannot tell their table; they need a slug of their own before the production migration makes them.
- No code reads a file type's `data.class`; gppufs picks a file's handler from gppu's own list, and gppufs works without the database.
- Session Manager and the admin's session pages cite `Linked Data - Sessions and work`, a superseded generated note.
- gppu has no public field for the first line a person typed; the session tools read it from `normalized_name`.
- RAN `Systems/lake/plaud/test_dagster_incremental.py` calls `download_recordings` with the signature CRAP d1091211 (2026-09-24) replaced.
- RAN `Systems/lake/m365/locations/karelin.py` and `tulaco.py` need a `lake.yaml` that is not in the repository; their compose services are commented out.
- RAN `Systems/lake/tests/test_age.py`, `test_catalog_graph.py` and `test_graph_read.py` run inside a transaction on pg.karel.in/everything; not run.
