# gppufs: decisions for Alex

gppufs is becoming a standard fsspec file system: a URI starts it, one instance serves every path, and an index beside each folder holds what the handlers read. Three questions are left that only you can answer. Each one names the work it holds up and the option that works. Answer on the `Answer:` line.

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

## Settled by what you said, not questions

- **A file's UUID is computed from its URI**, because you said a URI determines its UUID and nothing assigns itself an identifier. The same URI gives the same UUID on every machine without asking anything. When `mv` moves a file, gppufs carries what it read to the new UUID, the way it carries index rows today. The UUID starts with the shard of `fs.files`, `0x1002`, from your Linked Data FS standard.
- **There's one gppufs in a process.** Nothing creates a second one, and folders whose index stays in the cache are an option of that one gppufs.
