# Handlers — 13 tasks, 2026-09-04

Evidence and measurements: `FEEDBACK_HANDLERS_260904.md`. Lake side: `D:\Dev\CRAP\Systems\Lake\PLAN_HANDLERS_260904.md`.

## gppu — 1 to 6

1. Make `SessionHandler.identify_sync` check extension and size before opening the file.
2. Make `ArchiveHandler.identify_sync` consult `ArchiveHandler.extensions` before the zip, rar, gzip and tar signature checks.
3. Stop `SessionHandler.identify_sync` head-reading every child when asked about a folder. That is the second read of every file — measured at 2.33 `_head` calls per file, 352 of 820 being repeats.
4. Add `walk_sync` (generator) and `walk` (async generator), both taking `enter` and `on_folder_done`.
5. Have `identify_sync` and `probe_sync` consume the walk instead of building a list plus two dicts.
6. Have `archive_path_sync` ask for the root record only, not the whole hierarchy.

1 to 3 are the cost: 1,214 µs an entry against 6 µs for `os.walk`, which is about half an hour of identification across the lake's 1.7 M entities on a pass that stores nothing new.

## Lake — 7 to 13

Blocked until gppu is built and installed on alex-pc.

7. Add `Systems/Lake/handlers.py` with `LakeHandler(FileHandler, IgnoredHandler, MarkdownHandler, SessionHandler, ArchiveHandler, FolderHandler)`.
8. Delete `EXCLUSIONS`, `FOLDER_CLASS_RULES`, `HIDDEN/SYSTEM` and `_folder_class()` from `indexer.py`.
9. Delete `_probe()`'s try/except and the `unread` key; read `Record.errors`.
10. Replace `_folder()`'s recursion with `walk_sync(enter=..., on_folder_done=...)`.
11. Switch `probe` and `invalidate` to `probe_sync` and `invalidate_sync`.
12. Restore the broken-markdown check in `demo()`.
13. Add git spans per repository root, one call each, not during the walk.

13 is new behaviour, not a move.
