---
fileClass: Document
created: 2026-09-22
updated: 2026-09-22
generated: { by: Codex/GPT-6, at: 2026-09-22 }
---
# Indexing through Containers

`catalog.location(uid).container(path).walk(...)` enumerates a selected Container for an index consumer. gppu owns source access, exclusions, handler readings and archive extraction. The consumer owns persistence, run state and progress. No database or adjacent cache is created by this operation.

Alex, 2026-09-22: "Correctly implement containers and locations so file indexer works via gppu"

`Location.ls()` enumerates child Locations. `Location.container(path)` selects a Container. Container folders remain contents; traversal never creates configured Locations. `Location.uri_of(path)` returns the escaped canonical source URI without exposing a physical path to the consumer.

`Container.walk(path='', level='files', recursive=False, boundaries=())` yields `(folder, entries)` after the folder has been successfully enumerated. Entries use Container-relative `name`, fsspec `type`, `size`, and provider or handler metadata. A listing error raises before a complete folder is yielded. Explicit child Location boundaries are reported but not entered.

The September FileIndexer's levels remain: `refresh` records folders; `files` adds file metadata; `handlers` adds recognized content readings; `archives` also opens archive contents. A handler failure is retained as `unread` evidence. An archive is never opened below `archives`. Selected archive members are extracted once per archive under the platform cache and removed when the iterator closes. Session readings retain their native fingerprints.

The file implementation uses the established gppu handlers. It records links without following them, and keeps the existing folder class and ignore rules. Its traversal never resolves a host-only file Location or a Windows drive-relative path against the process working directory.

The default non-file implementation uses the Container's `ls` and `read` methods. It validates immediate relative children and retains DataObject URI and native identity. It does not pretend that an API object is a filesystem file.
