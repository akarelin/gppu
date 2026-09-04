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
