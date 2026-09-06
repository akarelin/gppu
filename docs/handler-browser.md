---
fileClass: Document
created: 2026-09-05
updated: 2026-09-05
generated: { by: Codex/GPT-6, at: '2026-09-05 2310' }
---

`examples/handler_browser.py` demonstrates async handlers, persistent local indexes, and the shared `gppu.tui.TreeTable`.

Run `python -m examples.handler_browser` from the repository in its virtual environment with the `tui` extra installed. It starts in the current directory with no arguments or new configuration. Arrows or Enter expand folders; Backspace browses the parent; `i` creates or refreshes the selected folder's index, or the containing folder when a file is selected; `q` exits.

Each folder is indexed separately, one level at a time. Folder counts and size describe direct children; the span combines the probed files' handler spans. Browsing checks the folder's `_persist.db` first and uses its saved listing without invoking filesystem handlers. An unindexed folder uses async handler identification and traversal. Explicit refresh probes files and replaces that folder's saved listing, discovering additions, changes, and deletions. The Source column identifies index and filesystem observations; an index is a snapshot, not a claim of current filesystem state.

The example reuses `ListingHandler` from `handler_ls.py`. It saves display metadata through `gppu.data.Persistence` using SQLite and its native `_persist.db` filename, in a separate `HandlerBrowser` namespace. Entries use relative paths. Source text and typed handler objects are not persisted. Browsing does not create indexes, the database is excluded from its own listing, and refreshing preserves other persistence namespaces.

Handler operations are awaited. SQLite open, read, write, and close run in `asyncio.to_thread`; Textual coroutine workers keep the interface responsive. A failed read or refresh is displayed as an error. SQLite replaces the saved listing atomically; a failed write leaves the previous snapshot intact. The shared table preserves selection and expansion while the refreshed branch updates.

The only library change gives TreeTable's left/right bindings priority over DataTable horizontal scrolling, so expansion works when metadata columns overflow the terminal width.
