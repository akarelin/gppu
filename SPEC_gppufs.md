# gppufs: Alex's instructions

What Alex instructed for gppufs, its catalog and their users, as plain statements. The Linked Data standard is `D:\_\_Standards\Linked Data\Linked Data.md`, the one note marked active, and it alone is canonical for Linked Data itself; the other notes there are not specification; how gppufs uses Linked Data is gppu's product. `D:\_\_Standards\Systems\gppufs.md` and `Lake.md` are generated and are not specification.

## The file system
- gppufs is an fsspec file system, registered as `gppu`. It wraps any file system fsspec reaches, as fsspec's caching file systems wrap theirs.
- gppufs is a full file system: it is initialized and used as any fsspec file system, copying, moving and the rest included. What it adds is richer indexing and distributed indexing. A deviation from fsspec's behavior is Alex's decision.
- One gppufs serves every path and finds the index from each path. Nothing makes a second gppufs.
- Settings are options; the cache folder holds an index only when asked to.
- A URI initializes gppufs: it says what file system gppufs wraps and which parts of gppufs to start. After that gppufs is called with a path in any form.
- Inside gppufs everything is a UUID. A URI determines its UUID and carries more information; URIs are for initializing gppufs and for handlers.
- The handler generates the UUID of what it reads. It is an instance's or a file's by the handler's target; an instance is one copy of a file at one path.
- gppufs separates files from instances: what it indexes at a path is an instance, in fs.instances.
- gppufs works without the database and knows nothing about locations or the database.
- gppufs can read where the catalog is from configuration; by default there is no catalog. With a catalog, gppufs lists and opens through it what it holds no index for, SharePoint and archives among them.
- gppufs and the gppufs catalog are two file systems.
- gppu/fs redefines y2uri so that every form the URI convention lists is read and written back as it is, and fsspec opens it.

## Linked Data in gppu
- Files are in the `fs` (File System) schema; its records are `gppu.fs.files`.
- A record's type is its type's slug, text.
- Inside every schema, types describe how the rest of the schema works: the type made for one of the schema's tables says what it holds, and the types under it are its kinds. The types and their parents are those of `Linked Data.md` # Types.
- A type's parent is the type it is under, a container of types, not inheritance.
- Status is a Constrained Vocabulary stored in Linked Data, and each type has its own list of statuses.
- A task's parent is a project or another task.
- A record of the `ld` schema has a kind, as it has a status: each type has its own Constrained Vocabulary of kinds, so a type is not split into types per kind. Experiment, feature, problem and chore are kinds of work. Other schemas have no kind until they need one.

## The catalog and its users
- gppu provides the catalog; the catalog's users load its locations.
- Linked Data and the file system stay separate, each in its own submodule.
- Writes to Linked Data go through its API, never directly into the database.
- Objects are retrieved and saved by uri; the Lake decides where an object goes.
- The Lake is storage for all file-like objects: the main lake `\\s1\Lake`, the text lake `D:\TextLake`, which is part of it, and lake-in-place at various locations.

## Users
- Every user of gppufs is moved to it: the Lake, the admin UI and its APIs, Linked Data, Session Manager, and every service deployed in Docker that uses it. The web services gppu implements and its users deploy keep working.
- The session cleaner uses gppufs's handlers, listing and moves, and runs in gppu's TUI with its display of sessions and its background control.
- Tests go through a real database.
