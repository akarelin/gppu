# Desktop filesystem

Requirements: [SPEC_desktop.md](SPEC_desktop.md). This phase is done when its three use cases work.

## Use cases
- done: rich information: a session the handler read is shown by its handler's name (start, turns, length, topic), its span the entry's created and modified times; proven on the virtual filesystem over `C:\Users\Alex\.claude\projects\D--Dev-CRAP`, read from the local index after a FileIndexer handlers run, a session read back by its shown name; G: gives Windows the span's start as the creation time
- done: SharePoint libraries browsed from the index, without touching SharePoint; live at `api.karel.in/lake/catalog` since 2026-10-22 10:00, proven on the virtual filesystem and on G:
  - The index: the Lake catalog (pg.karel.in `files`, schema `lake`) holds source `sharepoint`, 162,802 entries read on 2026-09-18 with each item's content type and columns, a tree by id (`entity.parent_uid`); Linked Data holds the libraries as locations with the catalog's id in `meta.lake_id`.
  - Done: `gppu.catalog`, the catalog's API at `/lake/catalog`, served by stack lake with `/lake` (CRAP `Systems/lake/serve.py`); a folder's entries stream a line at a time from a server-side cursor, so the largest folder, 56,297 entries, is never held whole. `CatalogFileSystem` browses it by ids, and the desktop shows it as the Catalog folder (`examples/desktop_mount.py`).
  - Proven against `api.karel.in/lake/catalog`: `Catalog/M365/Karelin/sharepoint/sites/Suntrust/Statements` lists its files with SharePoint's Created and Modified, and the largest folder streams whole.
  - done: each entry's content type and columns: a listing carries the text of its columns, those SharePoint gives some items and not every one (`Catalog.columns`), and `GET /entries?path=` lists a folder by the path the desktop shows; Directory Opus reads them with the Catalog Columns add-in (RAN `Hosts/W11/DOpus/Script AddIns`), and the folder format saved for `G:\Catalog` and its subfolders shows Content Type, Start Date, End Date, Tax Year, Company, Kind, Classification and Date; proven on Suntrust's Statements and its Tax Forms (2026-10-22)
- done: Projects and Work shown from the index, each task or project once by its own name with its span; proven on the virtual filesystem and on G: over `D:\Work` and `D:\Projects`. gppufs reads them with `WorkFolderHandler` and `ProjectsFolderHandler` on `PartitionedFolderHandler`, which say which folders are date partitions and a thing's own name; a task's archived stages are part of it, ignored entries are left out, and a file a task keeps on several days is shown as its latest
  - A task's or project's span is that of its files in each place it is kept, one aggregate in the index (`GppuFileSystem.spans`), after FileIndexer indexed Work and Projects at the files level (2026-10-22); a folder the index has listed is answered from the index alone. G: gives Windows the span's start as the creation time.

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
- the API region, the server's index through Linked Data and the Lake's API, joined with the local one
- the Lake's own read side: a handler for its date layout, beside the templates `gppu.lake` saves by

## Found, unrelated
- tests: `tests/test_tui_progress.py`'s process-row test fails in some full-suite runs and passes alone
- gppufs: `_misread` probes (stats) every known subfolder on every live listing; probe picks a folder's handler from its path alone
- the Lake's API: SessionHandler fails reading some sessions it saves, `AttributeError: 'list' object has no attribute 'replace'`
