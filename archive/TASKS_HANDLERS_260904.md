# Handlers — 6 tasks for gppu, 2026-09-04

Evidence and measurements: `FEEDBACK_HANDLERS_260904.md`. Every file named here is in this repository.

1. Make `SessionHandler.identify_sync` check extension and size before opening the file.
2. Make `ArchiveHandler.identify_sync` consult `ArchiveHandler.extensions` before the zip, rar, gzip and tar signature checks.
3. Stop `SessionHandler.identify_sync` head-reading every child when asked about a folder. That is the second read of every file — measured at 2.33 `_head` calls per file, 352 of 820 being repeats.
4. Add `walk_sync` (generator) and `walk` (async generator), both taking `enter` and `on_folder_done`.
5. Have `identify_sync` and `probe_sync` consume the walk instead of building a list plus two dicts.
6. Have `archive_path_sync` ask for the root record only, not the whole hierarchy.

1 to 3 are the cost: 1,214 µs an entry against 6 µs for `os.walk`, which is about half an hour of identification across the lake's 1.7 M entities on a pass that stores nothing new.

The seven follow-on tasks belong to the lake and touch nothing here. They are in `D:\Dev\CRAP\Systems\Lake\PLAN_HANDLERS_260904.md`.

## Two more, measured while moving the consumers onto the new handlers — 2026-09-04

7. Stop `full_path()` resolving a path that is already absolute on every handler call. `children()` gets absolute paths from `iterdir()` and then each of the five handlers in a composed set calls `full_path()`, which ends in `result.resolve()`. Measured over `D:\Dev\CRAP\Systems`, 403 entries, alex-pc, Python 3.14.7: 2,461 `realpath` calls for 403 entries, `nt._getfinalpathname` 0.137 s of 0.286 s and `full_path` 0.206 s of it — 72% of identification. The set costs 505 us an entry against 4 us for `os.scandir`, and tasks 1 to 3 have already been done; this is what is left.

8. `call_sync` must not reach `self.identify_sync` on a composed handler. `FolderHandler`, `MarkdownHandler`, `CSVHandler`, `LogHandler` and `EmailHandler` all open with `if not self.identify_sync(path)`, and on a composed set `self` is the `FileHandler`, so that call is `FileHandler.identify_sync(path, recursive=True)` — a full recursive identification of everything below the path, whose non-empty list then reads as true. `FolderHandler.call_sync` over `D:\Dev\CRAP\Systems`: 0.000 s on `FolderHandler()`, 0.214 s on the composed set, and `probe_sync(folder, recursive=False)` pays the same 0.197 s to probe one folder. A file root is cheap by accident; a folder is not.
