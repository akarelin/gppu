---
fileClass: Document
status: draft
created: 2026-09-18
updated: 2026-09-18
generated: { by: claude/opus-5, at: 2026-09-18T03:45 }
---

# Handlers

**Written by an agent on 2026-09-18. Alex has not read it, so it is not authoritative. When he has read it and approved it, this line will say so, and this document is then the source of truth for handlers.**

What is implemented, what is left to implement, and what is built against a rule. Every statement about the running code names the file, the line or the measurement that proves it, read from `gppu/handlers.py` rather than from `docs/handlers.md`, which is generated from the signatures.

His own text is preserved unchanged and is not edited: `D:\_\_adrs\ADR001 - Session file naming convention\SPEC_handlers_gppu.md`, which he wrote himself and marked active, and `D:\_\_adrs\ADR001 - Session file naming convention\ADR001 - Session file naming convention.md` beside it, also his.

---

# Implemented

## What a handler is

- A handler identifies what a file or path is, probes it, and loads data.
- A handler receives one path and returns statistics and a typed object; the statistics are derived from the complete typed object.
- A caller composes the handlers it wants by ordinary multiple inheritance, and the composed class is the access point.
- `FileHandler` means the File and Folder handler, and is the access point to the rest.
- A record is a single instance of a file or a folder with its metadata: path, whether it is a folder, size, modification time, the names of the handlers that matched, the probes, the statistics and any errors (`Record`, `handlers.py:377`).
- Statistics on a hierarchy are file count, folder count, byte count and span (`FileStats`, `handlers.py:367`).
- Every handler copies the metadata mapping its caller gave it, so a later change to the caller's dictionary does not change results (`handlers.py:271`); where a key is in both, the caller's wins.
- A read failure does not stop a scan. It becomes a `HandlerError` on the probe and on the record. A handler built with `strict=True` raises instead.
- The thirteen handlers that name themselves: folder, ignored, sqlite, file, git, archive, markdown, csv, log, email, browser-history, session, location.
- Archive members are records like filesystem entries, with the archive in `location`.
- An ignored folder stays visible and is not descended into.
- The git handler reads local history and configuration only, and never contacts an upstream.

## The three methods

- `identify(path, recursive=True)` returns the root and its descendants with the handlers that match each, and loads no typed objects (`handlers.py:790`).
- `probe(path, recursive=True)` identifies, then loads the matching handlers and accumulates folder statistics from the descendants (`handlers.py:835`).
- `normalize(source, destination=None, recursive=True, exclude_handlers=())` renames in place using the first matching handler that defines `normalize_name`. With a destination, his specification reads: "If provided - copy into new structure." The hierarchy is written there and `.git` is excluded (`handlers.py:1053`).
- Each is awaitable inside an event loop and returns directly outside one; the `*_sync` methods are the strict implementations.

## Files and folders

- The default file handler gives file metadata and the list of handlers that match a file, the filename including its full path.
- The default folder handler gives folder metadata and the handlers that match the folder.
- A folder probe aggregates the statistics of its child files and folders, and its span is the earliest and latest timestamp anywhere in the records.

## Sessions

- The session handler identifies the harness from the first 8 records of a log (`SNIFF`, `handlers.py:108`).
- Nine harness names are carried: chatgpt, cx, claude, cc, gemini, agy, hermes, openclaw, manus (`handlers.py:90-98`), which is the list in his naming convention, in his order.
- What produces each of them is the code's decision and is in neither of his files. His convention writes `chatgpt | cx`, `claude | cc` and `gemini | agy` as pairs, and his field is `{model|harness}`. Six are native log recognizers — cx, gemini, cc, openclaw, agy, hermes (`handlers.py:4031-4037`). Two are export handlers — `chatgpt` from a ChatGPT export and `claude` from an Anthropic one (`handlers.py:3787`, `:3900`). So two of his pairs are read as an export and a native log, and the third, gemini and agy, as two different native harnesses.
- `manus` is his own reserved name from his convention and nothing produces it.
- A session record carries harness, uid, parent uid, whether it is a subagent, the original source objects, the normalized turns, span, models, topic and whether it is sidechain only (`SessionFile`, `handlers.py:3423`).
- `probe` gives one record per session and one for the folder holding them.
- A folder's own uid is the shared session id only where every identified id agrees (`SessionFolder.uid`).
- A session folder holding more than one harness is refused (`handlers.py:4113`).

## The session filename

His convention, `D:\_\_adrs\ADR001 - Session file naming convention\ADR001 - Session file naming convention.md`:

    {YYMMDD-HHMM} {turns}~{last-first} {tags} - {Topic}.{guid}.{ext}

- Built as `{YYMMDD-HHMM} {turns}{~last-first} - {Topic}.{uid}{suffix}` (`SessionFile.label` and `SessionFile.name`, `handlers.py:3498-3513`).
- The duration is one unit, days, hours, minutes or seconds, and is omitted where the span is empty (`UNITS`, `handlers.py:115`).
- The complete name is held to 254 characters and only the label is cut, so the id and the extension survive (`NAME_LIMIT`, `handlers.py:117`). His convention allows only the topic or title to be cut, and the code could cut further, though nothing in either live store does: a uuid tail is 43 characters, so the cut falls at 211 against a prefix of 17 or 18 ahead of the topic, and reaching past the topic would need a session id of about 230 characters where the longest any harness produces is 36. Run over both stores, 75 of 1,629 parsed names are cut and every cut lands in the topic.
- `normalize_name` refuses a session with no immutable id, a folder of sessions, and an exported session read out of a zip (`handlers.py:4119`).

## The file system over the handlers

- `GppuFileSystem(location)` composes the implemented parsers behind fsspec `ls` and `info`, with SQLite metadata indexes beside the source folders (`handlers.py:5132`).

---

# To do

- **`{tags}` in the session filename.** His spec marks tags RESERVED and his convention lists them as optional hashtags before the topic. Nothing builds them, and `SessionFile` carries no tags field.
- **Assets and subagent folders.** His convention: a session's assets belong in a folder named exactly like the filename without its extension, and a subagent's text in a folder named like the filename with the extension set to the agent uid. Neither is built; the word asset does not appear in `handlers.py`.
- **The path convention.** His convention puts the harness or model in the containing folder, `.../{model}/{session-file}`, and says the path carries provenance that the filename should not repeat. `normalize` with no destination renames the file where it stands and does not place it under a harness folder.

---

# Errors

- **The sqlite handler is available and unused.** It names itself here, and `CRAP/Systems/Lake/import_indexes.py:126` opens the stranded SQLite indexes with `sqlite3.connect` instead. The claim that everything reads through these handlers, and the second place it does not hold, are recorded in `CRAP/Systems/Lake/LAKE.md`.
