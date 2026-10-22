# Desktop filesystem

Requirements: [SPEC_desktop.md](SPEC_desktop.md). This phase is done when its three use cases work.

## Use cases
- done: rich information: a session the handler read is shown by its handler's name (start, turns, length, topic), its span the entry's created and modified times; proven on the virtual filesystem over `C:\Users\Alex\.claude\projects\D--Dev-CRAP`, read from the local index after a FileIndexer handlers run, a session read back by its shown name. On G: Windows' Created column is left at 1970: the wrapper does not pass the creation time
- in progress: SharePoint libraries browsed from the index, without touching SharePoint
  - The index: the Lake catalog (pg.karel.in `files`, schema `lake`) holds source `sharepoint`, 162,802 entries read on 2026-09-18 with each item's content type and columns, a tree by id (`entity.parent_uid`); Linked Data holds the libraries as locations with the catalog's id in `meta.lake_id`.
  - Done: `gppu.catalog`, the catalog's API at `/lake/catalog`, served by stack lake with `/lake` (CRAP `Systems/lake/serve.py`); a folder's entries stream a line at a time from a server-side cursor, so the largest folder, 56,297 entries, is never held whole. `CatalogFileSystem` browses it by ids, and the desktop shows it as the Catalog folder (`examples/desktop_mount.py`).
  - Proven in-process on the virtual filesystem over the real catalog: `Catalog/M365/Karelin/sharepoint/sites/Suntrust/Statements` lists its files with SharePoint's Created and Modified.
  - Next: deploy stack lake's new image, then prove it on the virtual filesystem against `api.karel.in/lake/catalog`.
- not started: folders partitioned by date, such as Projects and Work, shown as stored, with a filter by date

## Done
- Complete: recover prior work and verify fsspec and Windows integration.
- Complete: implement and prove a desktop mount using gppufs navigation and reads.
- Complete: run the Lake mount and verify desktop browsing.
- Complete: implement coexisting physical and indexed views, including direct access to deep indexed files.
- Complete: verify live indexed reads and visible Directory Opus contents; document and publish the implementation.
- Complete: the sources are every location Linked Data knows that this host reaches, with `desktop.yaml`'s; their indexes and those of the folders directly inside them are under `Indexed`.
- Complete: Windows lists every file an index holds: ignored files left out, an archive member named without the chain's colons and given its time in seconds, a name cut to Windows' 255 characters at the end nearest the file.
- Complete: the Indexed view opens an index only while it reads it, so gppufs can replace an index whole (2026-10-22).

## Independent and unscoped
- the API region, the server's index through Linked Data and the Lake's API, joined with the local one; the Lake's API is not served until its stack exists
- the drive is stopped since 2026-10-22, being redundant for now
