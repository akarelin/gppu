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
- catalog() reads location records as gppu.fs.files has them; a location is on this host by its handler's access, or below the location above it: done
- gppu.ld to the Linked Data standard as it is now (two-byte ids, shard1 the schema and shard2 the table, from `Linked Data.md`; its SQL and Python first copied from the LD, FS and Sessions notes, which are generated): done, its tests pass on Postgres
- gppu.ld checked against `Linked Data.md` alone: flags change only by its transitions, `delete` among them; a record's children listed by `records_list`; every schema's root types at the root of their schema, none under another schema's types; a link written as any record is, its ends and its type not checked, which were the agents' rules; code and SQL cite `Linked Data.md` and gppu.ld, not the generated notes; `type` stays text; ids, span, shard codes and slugs already matched: done, the gppu, FileIndexer and admin suites pass on the scratch database

## Users of gppufs, moved in parallel (docs/gppufs-users.md)
- Lake service and Dagster (RAN `Systems/lake`, stacks `lake` and `dagster` on trix): done; both code locations build, 118 tests pass
- Linked Data service (RAN `Systems/ld`, stack `linked-data` on five), session hook and Session Manager: done, its sessions on gppu.ld.sessions and its checks on `/fs` pass on a scratch database; a session's messages read in their file's order: done; its core check, its pages (stack linked-data's `admin`) and `structure.py` (knowledge, a node type) on the new records: done, the pages built and type-checked, their browser check waiting on WSL's network; Session Manager's plain links are type `link`; serving waits on the gppu release and gppu.ld's SQL on its database
- FileIndexer (RAN `Systems/ld/fileindexer`): done, posting locations as gppu.fs.files has them; its tests pass on Windows against a scratch database
- Admin UI and its APIs (CRAP `Systems/admin_ui`; RAN `Services/admin-ui`, `Services/admin-priors`): done; its configuration routes answer as the live API does, its tests pass as the running image's do, its docs page renders; its Linked Data record pages on the new API: done, drawn in a browser against a scratch database; the work, project and knowledge pages wait for `/work`'s schema, Systems and Processes for the entity types they filter by
- gppu.ld: a sort by span, a type's update without its slug and shard, a link's type checked against the store's types, removed again as a rule Alex did not write: done, its tests pass on Postgres
- Host tools (RAN `Hosts/preservator`, `Hosts/tui` session scripts): done, preservator saving through the Lake, `platform_for_os` restored
- Releases and deploys of the stacks: a gppu release from master, Alex's
- with a catalog, gppufs lists and opens through it what it holds no index for, SharePoint and archives among them: done; the catalog's address is the `catalog` option, from fsspec's configuration (`FSSPEC_GPPU_CATALOG`), none by default; bytes come from the Lake at the entry's address
- each index row carries a UUID, made by gppufs as an instance's (`uuid_create(0x1003)`), rows indexed with a file's id given an instance's, kept through a refresh, a change and a move: done; an index on a store this host does not own holds its ids in memory until its own host writes it; finding an entry by its UUID: not started
- the handler generates the UUID, an instance's or a file's by its target: not started; which handlers target which is in the gppufs note's "For Alex to decide"
- the gppufs and Lake notes in `Linked Data.md`'s style, conventions from the spec and the code, then their processes, life cycles and types as unverified details; the earlier text of each its Implementation note: done
- gppufs on fsspec's `AsyncFileSystem`, its callers moved: done in gppu and RAN, the suite passes, the session cleaner's dry run finds the same sessions; the admin API's inventory readers await `_ls` and `_info`: done
- the catalog's Location binds this host's folder for a location reached through `handler.access`, not the canonical's: done
- the Lake keeps its index at its root, never in its day folders: done, as the Lake on s1 already has it

## In progress: gppufs and gppu.ld on master
What matters is gppufs working, and its code merged so the new Linked Data, gppu.ld, works on top of it.
- `ld-standard` into master as a fast-forward, the whole suite passing on the scratch database: done; gppu's work goes to master.
- Every user of gppufs on master and pushed: done; vfs, the desktop, the handler browser, the session cleaner, the Lake and Dagster, the Linked Data service, the session hook, Session Manager, FileIndexer and its TUI, the admin UI and the host tools already ran on it, their tests passing; CRAP `Projects/FileIndexer`'s tests import `GppuCatalog` from `gppu.fs.catalog`; RAN `Systems/ld/ld.sql` is gppu.ld's SQL, and the Linked Data image installs every module gppu.ld needs from master
- RAN `.github/workflows/ld.yml` building from `Systems/ld`: on RAN's master; it runs only when Alex starts it, and has not run
- The `fs` (File System) schema's records back in `gppu.fs.files`, where the standard puts files, and every importer moved to it: done; the gppu suite and FileIndexer's tests pass on the scratch database, the Linked Data API imports
- Production Linked Data, https://api.karel.in/ld/v1, serves the API from before the standard, with no `/fs`: checked 2026-10-29; gppu.ld and gppu.fs.files run on the scratch database only.
- No workflow runs on a push; a release and the deploys stay Alex's. RAN's Linked Data and Lake images install gppu from master, so their next build takes gppufs and gppu.ld, which need gppu.ld's SQL on `linked_data` first.

/goal gppufs and gppu.ld are on gppu's master and every user of gppufs is updated to it and pushed; proven by the gppu suite and each user's tests passing against the scratch database; no release, deploy or production write.

## URI convention and Linked Data 0.2
- gppu/fs's y2uri (`gppu/fs/uri.py`): `uuid:` and any uri without `//`, fsspec's chained uris with their target, a path joined below, and what a fragment selects (anchor, text, line, char, t): done; tests/test_uri.py opens a zip member, a `gppu::` file and a `file:///` file through fsspec, and the whole suite passes

Independent, not scoped:
- `rar:` registered with fsspec
- `lake:` and `m365:` registered with fsspec
- addresses in the schemes the convention discards still in use: the Lake's `pg://`, gppufs's `catalog://`; `gppu-catalog`, `gppu-index` and `gppu-desktop` are only fsspec's names for those classes, no address uses them
- a `uuid:` resolved to its record
- a record's `name` and `display_name` as 0.2 has them
- a type's slug as its alternative key
- the initial types of 0.2 in ld.sql
- the Lake's sections: Activity by source, `text`, `inbox`

## No ld.records and no /records
- gppu.ld: each table carries a record's columns itself and is served at its own path (`/types`, `/nodes`, `/links`, `/events`); children and links are a search of their table: done, the gppu suite passes
- RAN `Systems/ld`'s scripts and checks on each table's path: done; check.py, check_files.py and structure.py pass against the API on a scratch database, FileIndexer's tests pass
- RAN `Systems/ld/web` on each table's path: done; type-checked, built, and drawn in a browser against the API on a scratch database, a record's links read from every schema's links
- CRAP admin_ui's Linked Data pages on each table's path: in progress
- no table inherits another: fs's and sessions' types and links are their own, each schema searched at its own paths: done, the gppu suite passes

## Nothing on the API from before the standard
Every caller of production's API from before the standard is moved onto gppu.ld on master; what runs live switches with production.
- the standard's initial types in ld.sql (work, epic, project and task events; entity and work statuses): done, the gppu suite passes
- a kind on ld's nodes and events, each type's kinds a constrained vocabulary as its statuses; experiment, feature, problem and chore kinds of work in place of the types per parent: done in gppu.ld, the suite passes; the carry-over, the collector, the callers and the pages on it: in progress
- RAN `Systems/ld`'s check_work.py, check_sessions.py and check_api.py on gppu.ld, work as events with a work's work and parents in work.py: done, every check passes against the API on a scratch database; web/check.py's page side: in progress
- the carry-over of production's store into gppu.ld through its API (migrate.py, migrate_systems.py), proven on scratch stores laid out as production's: in progress
- RAN `Systems/ld/ui`, retired 10-19 for admin_ui's Linked Data section, archived at RAN `archive/Systems/ld/ui-261029`: done
- every other caller (session hook, Session Manager, linked-data-tasks, the dashboard mod, MCP United's `pm_*`, static sites' lectures, Kuma's monitors, admin_ui's `shared`), and the list of what switches with production: in progress

## Found, not this task
- `examples/handler_ls.py` and the handler browser's `main` stop: `D:\TextLake\.catalog`, the catalog `examples/handlers.yaml` names, has no folder for this host, which the host-folder catalog has required since 2026-09-08, the day the folder was last written.
- The admin API's image installs gppu from the `gppu/latest` tag; the Linked Data and Lake images install it from master.
- WSL's mirrored networking gives its VM no network device on this host; WSL runs in NAT mode, reaches Windows and is reached at localhost, and Windows does not forward its traffic further.
- The admin's Linked Data pages count records with one request per type, about 60 on a store made from gppu.ld's SQL.
- The Lake API has no batch route: preservator makes two calls per file on every run, files already preserved included.
- FileIndexer could write files to Linked Data with `PUT /fs/files/{gppu.id}`; it writes none today.
- gppu.ld has what `Linked Data.md` does not define, from the generated notes: the columns `name`, `data`, `meta`, `created` and `updated`, and the API's routes.
- A record's status is not checked against its type's statuses.
- The Systems collector's runs were activities of subtype `collection`, which is the core's node type, so `POST /records` cannot tell their table; they need a slug of their own before the production migration makes them.
- No code reads a file type's `data.class`; gppufs picks a file's handler from gppu's own list, and gppufs works without the database.
- Session Manager and the admin's session pages cite `Linked Data - Sessions and work`, a superseded generated note.
- gppu has no public field for the first line a person typed; the session tools read it from `normalized_name`.
- RAN `Systems/lake/plaud/test_dagster_incremental.py` calls `download_recordings` with the signature CRAP d1091211 (2026-09-24) replaced.
- RAN `Systems/lake/m365/locations/karelin.py` and `tulaco.py` need a `lake.yaml` that is not in the repository; their compose services are commented out.
- RAN `Systems/lake/tests/test_age.py`, `test_catalog_graph.py` and `test_graph_read.py` run inside a transaction on pg.karel.in/everything; not run.
- RAN `Hosts/configure-all` imports `CliApp` and `Hosts/rewrite-commits` imports `file_log` from gppu; neither has been there since 3.6.24.
- RAN `Hosts/tui/tests`: `test_tui.py` expects the launcher's list from before pc-control, sessions-clean and configs-web; `test_start_page.py` loads a `start-page.py` that is not there.
- No workflow declares `LD_TEST_DSN`; the tests' Postgres is a scratch container in WSL Docker.
