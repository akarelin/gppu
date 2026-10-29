# gppufs: decisions for Alex

gppufs is becoming a standard fsspec file system: a URI starts it, one instance serves every path, and an index beside each folder holds what the handlers read. Four questions are left that only you can answer. Each one names the work it holds up and the option that works. Answer on the `Answer:` line.

## 1. What "refresh" means

**Holds up:** nothing yet. You asked to decide every deviation from fsspec, and this may be one.

In fsspec, `refresh=True` means "don't trust what you've cached, go back to the source." In gppufs, the index is the cache, and it holds what the handlers read. So gppufs's `refresh=True` re-reads the folder and runs the handlers on everything below it. That's how the session cleaner reads a finished session in full, and how the handler browser's "Refresh from source" key works.

- **A (today, works):** `refresh=True` re-reads the folder and runs the handlers. This is fsspec's meaning, applied to what gppufs caches.
- **B (works, needs a new word):** `refresh=True` only re-reads the folder, as it does in a plain file system. Running the handlers then needs a separate option of its own, and the session cleaner and the browser both switch to it.

Recommendation: A. It isn't a deviation; the thing being cached is just richer.

Answer:

## 2. What gppufs uses the catalog for

**Holds up:** gppufs reading the catalog's address from configuration, which you asked for. By default there's no catalog.

gppufs can't keep an index beside a folder it doesn't own: SharePoint, OneDrive, another machine's share. Those indexes can stay in this machine's cache, the same way the session folders' indexes do now. So gppufs doesn't need the catalog to work. The question is what it does when one is configured.

- **A (works):** gppufs sends what its indexes hold to the catalog as it lists. The catalog fills up wherever gppufs is used: FileIndexer, the session cleaner, the desktop.
- **B (works):** gppufs never talks to the catalog. FileIndexer reads the gppufs indexes and fills the catalog. In that case the catalog address in configuration is FileIndexer's, not gppufs's.
- **C (works):** gppufs asks the catalog about places it holds no index for, such as a share it can't read or a cloud drive it hasn't listed on this machine, and answers from the catalog's records.

Recommendation: B. gppufs stays a file system that knows nothing about the database, as you said, and FileIndexer remains the one thing that decides what goes into the catalog. C can be added on top later.

Answer:

## 3. Does the gppu library talk to databases directly, or only through the services' APIs?

**Holds up:** connecting gppufs, FileIndexer and Dagster's gppu code to the catalog and to Linked Data.

gppu holds both the code the services run (Linked Data's API and the catalog's Postgres reader) and the code their users run (gppufs, the Lake library, providers).

- **A (works):** only the services touch their databases. Every user (FileIndexer, the admin UI, Dagster and the small tools) goes through the API. There's one writer for each database to enforce its rules, credentials stay in the services, and schemas can change behind the API. The cost is speed on bulk writes, which batch endpoints cover. Linked Data's file endpoint already takes a whole folder in one call.
- **B (works):** users with database credentials write directly. It's faster for bulk loads, but each user then enforces the database's rules itself, and a schema change breaks every one of them.

Recommendation: A.

Answer:

## 4. Who writes into the Lake

**Holds up:** the Lake's place in the new structure, as a library and as a service.

The Lake has three parts, all in `gppu/fs/lake.py`:
- **The library, `Lake`:** decides where an object goes, saves it, and reads it with the handlers.
- **The service:** `/lake`, run by RAN `Systems/lake/serve.py`.
- **`LakeFileSystem`:** a read-only fsspec file system over that API, for browsing from anywhere.

The Lake folder lives on s1, and every machine reaches it as a share, trix included. gppufs never writes an index into a share. That's why the Lake's index is its catalog in Postgres, which the service keeps.

- **A (works):** only the Lake service writes into the Lake and its catalog. The library runs inside the service, and every other program saves through `/lake`. That matches answer A to question 3.
- **B (works):** any program that reaches the share uses the library and saves directly. Each one then writes the Lake catalog's database itself, which is answer B to question 3.

Recommendation: A. The Lake keeps one writer, and the client copy (a session hook growing its own copy) already goes through the API.

Answer:

## What changed for the Lake in this rework

- **Locations:** the Lake no longer fetches its locations from Linked Data inside gppu. The service reads Linked Data's location records and gives them to the catalog: `catalog(records)` for the locations, `Catalog(dsn, records)` for the Lake catalog. RAN's `Systems/lake/serve.py` has to pass them; that's a change to the service, waiting for your approval of gppu's structure.
- **Addresses:** the Lake names every row by its Lake address, the store's URI plus the path below it. gppufs used to do that through the location map. The catalog now holds that map (`locate`, `resolve`) for anything else that needs a location's address on a row.
- **One gppufs:** the Lake lists its folder on the process's single gppufs, the same one the catalog uses.
- **The Lake standard is out of date** in three places. It names `gppu.ld.gppufs.catalog()`, which is now `gppu.fs.catalog.catalog(records)`, fed by the service. It names `gppu/lake.py` and `gppu.catalog`, which are now `gppu/fs/lake.py` and `gppu.fs.catalog`. And it says the Lake's index is gppufs's index beside the Lake, which can't be, because the Lake is a share that gppufs doesn't write. Its index is the Lake catalog.

## How each user of gppu and the Lake fits

None of these has been changed yet: you said gppu's users wait until its structure is what you expect. This is what each one does today, and what changes for it.

- **Session hook** (RAN `AI/sessions/export_session.py`, run by Claude Code's hooks on every call): it doesn't import gppu. It asks the Lake API where the session's copy goes (`POST /lake/?copy`), grows the copy on the share itself, asks the Lake to index it (`POST /lake/{uri}`), and sends the new lines to Linked Data (`PUT /sessions`). It already works through the APIs, so nothing changes for it. On the service side, the Lake indexes the copy with its one gppufs.
- **Preservator** (RAN `Hosts/preservator`): it copies files from the fleet's hosts straight into the Lake folder named in `locations.yaml`, and uses gppu's session handlers to recognise sessions. It writes into the Lake without the service. With A in question 4, it saves the way the hook does (the Lake says where, preservator copies, the Lake indexes), so the Lake catalog knows what arrived. With B, it keeps copying and writes the Lake catalog itself.
- **Admin UI** (RAN `Services/admin-ui`): it browses through APIs only: the Lake's, the catalog's `/lake/catalog` and Linked Data's. Its Lake page still runs the earlier lake-api from CRAP's archive. The gppu rework doesn't reach it, and with A it stays that way.
- **FileIndexer** (RAN `Systems/ld/fileindexer`): it opens one gppufs per location. It moves to the one gppufs plus the catalog's location map: `reached` for the folders on this host, `locate` for each row's address, and `stats(path, apart=...)` to leave the locations below out of a location's totals.
- **Dagster** (RAN `Systems/lake`): it builds its catalog from its own configuration rows and runs the providers. That already matches `GppuCatalog(rows)`. It moves when the Lake service passes Linked Data's location records.
- **Session cleaner and desktop mount** (gppu `examples/`): already on the one gppufs. The session cleaner runs from the TUI launcher.

## Settled by what you said, not questions

- **A file's UUID is computed from its URI**, because you said a URI determines its UUID and nothing assigns itself an identifier. The same URI gives the same UUID on every machine without asking anything. When `mv` moves a file, gppufs carries what it read to the new UUID, the way it carries index rows today. The UUID starts with the shard of `fs.files`, `0x1002`, from your Linked Data FS standard.
- **There's one gppufs in a process.** Nothing creates a second one, and folders whose index stays in the cache are an option of that one gppufs.
