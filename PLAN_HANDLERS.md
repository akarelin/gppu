# Handlers

## Goal

Create one simple reusable system for files, folders, archives, and sessions, then remove duplicate traversal and parsing from its consumers.

## Alex's text

> Developer handlers that are human-readable and match my requirements. Handlers should be used to navigate, display and cache file hierarchy.

> Your task is to take out all spaghetti code from 100s of code files that work with files/folders/archives/sessions and create a simple reusable system of handlers from it.

> Negotiable if you can come up with a better approach or find flaws in my proposal

> Start small:
> cleanup-sessions
> store-sessions (or whatever is called as a hook form claude and codex)
> preserve-sessions

> Handler determins span of each file and span of each folder and span of final archive. preserve-llm-logs.py should not duplicate gppu.handlers

> I do not see any difference between file in file system, file in the cloud and file in archive

## Existing requirements

- The module is `gppu.handlers`; `FileHandler` is its access point.
- One input is a `Path` representing a file or folder.
- A handler returns `(stats, obj)`.
- `obj` is the complete typed representation; `stats` is derived from `obj`.
- A record represents one file or folder with information and metadata.
- Filesystem, cloud, and archive are locations; they do not create different file or folder types.
- `identify` returns file and folder records with every matching handler.
- `probe` calls matching handlers in order and aggregates folder counts, bytes, and span.
- `normalize` applies the matching handler's name or copies into a destination hierarchy.
- Database IDs, persistence, indexing, and SessionManager records are outside handlers.
- The same cached records supply navigation and display.

Sources: `D:\Dev\RAN\UO\KG\_Decisions\001 - Sessions - file naming convention\SPEC_handlers_gppu.md` and Alex's current Codex session on 260901.

## First slice

| Program named by Alex | Current program | Behavior retained |
| --- | --- | --- |
| cleanup-sessions | `D:\Dev\RAN\Hosts\sessions-clean.py` | Classify completed native Claude and Codex session groups and move only selected groups |
| store-sessions | `D:\Dev\RAN\AI\sessions\export_session.py`, deployed as `export-session.py` | Mirror native JSONL exactly during Claude and Codex hook events and render Markdown at session end |
| preserve-sessions | `D:\Dev\RAN\Hosts\preserve-llm-logs.py` | Collect declared Claude and Codex state from declared hosts and create the RAR named from the handler-derived hierarchy span |

These programs keep operation-specific policy. File discovery, typed session loading, derived statistics, hierarchy records, and cache come from `gppu.handlers`. The export hook's byte-for-byte copy remains standalone; its stored JSONL is handler input.

## Completion

- Cleanup and preservation use the shared hierarchy instead of implementing another traversal.
- The export hook copies native JSONL without loading a handler. Handler failure cannot prevent or undo that copy.
- Existing fixture behavior remains exact for JSONL mirrors, Markdown output, session cleanup classification, destinations, and preservation layout.
- The module's cached records supply hierarchy navigation and display data.
- Superseded parser and traversal code is removed rather than retained beside the new implementation.
