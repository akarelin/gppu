# gppufs: Alex's instructions

What Alex instructed for gppufs, its catalog and their users, as plain statements. The Linked Data standard (`D:\_\_Standards\Linked Data\`, the files marked `byAlex`) is canonical for Linked Data itself; how gppufs uses Linked Data is gppu's product. `D:\_\_Standards\Systems\gppufs.md` and `Lake.md` are generated and are not specification.

## The file system
- gppufs is an fsspec file system, registered as `gppu`. It wraps any file system fsspec reaches, as fsspec's caching file systems wrap theirs.
- gppufs is a full file system: it is initialized and used as any fsspec file system, copying, moving and the rest included. What it adds is richer indexing and distributed indexing. A deviation from fsspec's behavior is Alex's decision.
- One gppufs serves every path and finds the index from each path. Nothing makes a second gppufs.
- Settings are options; the cache folder holds an index only when asked to.
- A URI initializes gppufs: it says what file system gppufs wraps and which parts of gppufs to start. After that gppufs is called with a path in any form.
- Inside gppufs everything is a UUID. A URI determines its UUID and carries more information; URIs are for initializing gppufs and for handlers.
- gppufs works without the database and knows nothing about locations or the database.
- gppufs can read where the catalog is from configuration; by default there is no catalog. With a catalog, gppufs lists and opens through it what it holds no index for, SharePoint and archives among them.
- gppufs and the gppufs catalog are two file systems.

## The catalog and its users
- gppu provides the catalog; the catalog's users load its locations.
- Linked Data and the file system stay separate, each in its own submodule.
- Writes to Linked Data go through its API, never directly into the database.
- Objects are retrieved and saved by uri; the Lake decides where an object goes.
- The Lake holds only exact copies of what it preserves.

## Users
- Every user of gppufs is moved to it: the Lake, the admin UI and its APIs, Linked Data, Session Manager, and every service deployed in Docker that uses it. The web services gppu implements and its users deploy keep working.
- The session cleaner uses gppufs's handlers, listing and moves, and runs in gppu's TUI with its display of sessions and its background control.
- Tests go through a real database.
