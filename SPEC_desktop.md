# Desktop filesystem

Browse the data lake and other locations handled by gppufs from the Windows desktop.

Show contents in the way gppufs intends them to be browsed.

Use the integration most adjacent to fsspec. Directory Opus can use the filesystem.

Browse indexed folders based on the index, with access to deeper contents without browsing through very deep folders.

The virtual filesystem coexists with the filesystem, including SMB shares and synced folders.

The virtual filesystem is read-only for now.

The virtual filesystem is what is relied on, not the G: drive that wraps it.

Browsing is virtually instantaneous: it reads the local SQLite index, or the API that serves the Lake catalog.

The catalog's API is `/lake/catalog` for now. Its methods are specialized to working with the catalog, browsing it and these use cases, on a general foundation, and they handle very large data sets.

## Use cases

This phase is successful when these work in the virtual filesystem:

1. Rich information: a folder of sessions on a local disk shows each session's number of messages, its start and its span.
2. SharePoint libraries are browsed from the index, without touching SharePoint.
3. A folder stored partitioned by date, such as Projects and Work, is shown flattened: the date partitions are flattened and what they hold is shown correctly grouped. A project or task kept on several days is one project. Projects and Work show a well-structured view however messy they are inside, with GitHub repositories and hidden files among them, and projects kept in RAR archives show correctly.

An entry is shown by its own name. Its date is an attribute, a column of its own, never part of its name.

Any file manager that opens the virtual filesystem sees roughly the same thing: nothing is done in the file manager, such as Directory Opus.

## Regions

What is local is shown from the local indexes, through gppufs. The rest comes through Linked Data and the Lake's API, which serve the server's index; it holds more, and a local index can hold what the server's does not. The local region and the API region are one view, each entry once.
