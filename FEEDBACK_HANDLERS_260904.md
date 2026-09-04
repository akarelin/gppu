# Feedback on the new handlers — 2026-09-04

Two reads of `gppu/handlers.py` on `handlers-bigtasks`, morning and evening, against the one application that uses handlers: the lake's indexer, `D:\Dev\CRAP\Systems\Lake\indexer.py`. The module went from 2,516 to 3,829 lines between them. Everything below is the second read.

## Settled since the first read

- **Composition is public and caller-driven.** `class Lake(FileHandler, IgnoredHandler, MarkdownHandler, SessionHandler, ArchiveHandler, FolderHandler): pass` gives `['ignored', 'markdown', 'session', 'archive', 'folder']` off the MRO. No private base, no tuple to keep in step, and `metadata` and `strict` are per-instance. The lake can leave git out and add its own.
- **A failure is data, not the end of the scan.** `HandlerError` on `Probe.error` and `Record.errors`. A note whose frontmatter will not parse comes back as `errors=[('markdown', 'ValueError')]` and the recursive probe around it finishes. That is the lake's `metadata.unread` already in the library, and it makes the lake's own try/except redundant.
- **`.git` is visible again.** `children()` yields it with `handlers=('ignored', 'folder')` — recorded, not descended. `IGNORED_FOLDER_PATTERNS` is a superset of the lake's `FOLDER_CLASS_RULES`, and `IGNORED_NAME_PATTERNS` is its `EXCLUSIONS` exactly. Windows hidden and system are handled inside `IgnoredHandler`, so the lake's second `stat` for `st_file_attributes` can go.
- **`requires-python` is `>=3.14`,** which is what the PEP 758 syntax needs.

`EmailHandler` is new; `ImageHandler` and `VideoHandler` stand as placeholders.

## What is left

**Identify still opens every file.** Identify-only walk of `D:\Dev\CRAP\Systems`, 403 entries after ignored folders are skipped, alex-pc, Python 3.14.7, warm cache:

| set | per entry |
|---|---|
| `os.walk` | 6 µs |
| ignored + markdown + session + archive + folder | 1,214 µs |
| every handler | 9,170 µs |

| handler | per entry |
|---|---|
| git | 7,311 µs |
| session | 1,029 µs |
| archive | 534 µs |
| claude / chatgpt | 477 / 452 µs |
| email | 372 µs |
| log / markdown / csv | 364 / 352 / 351 µs |
| ignored | 282 µs |
| folder | 206 µs |

`markdown`, `csv`, `log` and `email` check a suffix. `session` and `archive` open the file. Measured on the same walk:

```
SessionHandler._head calls  820 for 352 files  = 2.33 per file
  of which repeat reads of the same file: 352
```

Every file is opened and JSON-parsed twice: `SessionHandler.identify_sync` on a folder lists it and head-reads every file in it to decide whether the folder is a session folder, then the walk enters and head-reads each file again for its own identify. `ArchiveHandler.identify_sync` adds `zipfile.is_zipfile`, `rarfile.is_rarfile`, a gzip check and `tarfile.is_tarfile` — for a `.py` as readily as for a `.zip`. `ArchiveHandler.extensions` exists and identify does not consult it.

A caller reading a Location at a level that never probes pays all of it. Extension or size first, the way the four new handlers do, is the difference between a 31-minute walk over the lake's 1.7 M entities and a 4-hour one.

**Git is seven times everything else together.** `identify_sync` walks every parent for `.git`, then `_history` calls `_state` — reads `HEAD`, reads the branch ref, stats `index`, `logs/HEAD`, `packed-refs` — once per path examined. It also turns both caches off on purpose: `record()` re-runs identify for git on a cache hit, `_probe_record` re-probes whenever git matched. Git spans are worth having on folders and on paths a caller asks for, not on every file a walk touches.

**There is still no public walk, and the two callers hold the tree.** `_walk` is private and yields `Path`. `identify_sync` returns `[self.record(f) for f in self._walk(...)]`; `probe_sync` builds that list plus a `records` dict and a `child_paths` dict. `recursive=True` is the default on both, so `probe(location_root)` holds the whole tree before the first record comes back, and `archive_path_sync` probes a complete hierarchy to read one span.

An iterating walk fixes it in both call modes, and gives a caller its progress indicator:

```python
def walk_sync(self, path, recursive=True, enter=None, on_folder_done=None):
    """`enter(record)` decides whether a folder is descended into; a folder it refuses is still yielded.
    `on_folder_done(record)` fires for a folder the walk went into and finished, and only for those."""
    for child in self.children(path):
        yield child
        if child.is_folder and recursive and (enter is None or enter(child)):
            yield from self.walk_sync(child.path, recursive, enter, on_folder_done)
            if on_folder_done is not None:
                on_folder_done(child)

async def walk(self, path, recursive=True, enter=None, on_folder_done=None):
    for child in await asyncio.to_thread(self.children, path):     # one thread hop per folder
        yield child
        if child.is_folder and recursive and (enter is None or enter(child)):
            async for found in self.walk(child.path, recursive, enter, on_folder_done):
                yield found
            if on_folder_done is not None:
                on_folder_done(child)
```

`children()` is where the syscalls and the identification cost sit, so that is the unit worth moving off the loop. Measured over 525 entries: 0.6 s either way, and a 50 ms spinner beside the async walk ticked 10 times, so the loop was never blocked.

`@sync` cannot wrap an async generator — calling one returns an async generator object, not a coroutine, and `asyncio.run` answers `TypeError: An asyncio.Future, a coroutine or an awaitable is required`. So the walk needs the two names the module already uses everywhere else.

`on_folder_done` stays a callback because a flat stream cannot say *this folder finished*: the folder was yielded long before the walk comes back up. The lake appends to `batch.entered` there, and that list is how it says a thing that was there and is not now is gone. `enter` refusing a folder while `on_folder_done` never fires for it is the same rule from the other side.

## Smaller things

- **`Record` carries no link.** `is_folder` is False for a symlink to a directory, so the lake re-checks `is_junction()` and `is_symlink()` and reads `os.path.realpath`. `record()` already computed `is_symlink`. Hidden and system are covered now; the junction target is not.
- **`_head` reads a whole line.** `for line in stream` on a one-line 2 GB JSON file reads 2 GB before the JSON check.
- **`SessionFile.records` keeps the entire parsed JSONL,** and `_probed` and `_session_cache` are unbounded. Probing a Sessions folder holds every parsed session at once. The lake's answer is `invalidate()` after every batch, which throws away the parts it still wants.
- **`_archive_children` scans the complete member tuple for each folder inside the archive** — members × folders. A RAR with 100k members and 10k folders is a billion comparisons.
- **`@sync` returns a Task inside a running loop.** `probe()` from sync code that happens to sit inside an event loop returns a Task, not records. The `_sync` twins are the safe call; the docs point at the decorated names.
- **`Record.path` is `Path | PurePosixPath` and `location` is `str | Path | None`.** Every consumer writes `isinstance` checks to find out whether it is looking at a real file.

## What `MarkdownHandler` does not carry

The frontmatter as written, `created..updated` as the span, and `title`, `name`, `tags` — everything the lake's own note handler did. What is missing is the mapping onto Alex's frontmatter standard: `fileClass` or `type` to `instanceOf`, `status`, `byAlex`, and the `up`/`down`/`prev`/`next`/`related` wikilink targets. That is a vocabulary, not a parser, and it belongs to whatever stores the annotations. Nothing is lost meanwhile — `MarkdownFile.frontmatter` holds every key.

## Measurements

Scripts in this session's scratchpad, each ~30 lines and re-runnable: `bench2.py` (per-handler walk timing), `heads.py` (head-read and sniff counts), `walkdemo.py` (iterating walk, sync and async, with a progress line), `review4.py` (error-as-data and the per-handler table above).

Host alex-pc, `D:\Dev\gppu\.venv` (Python 3.14.7), `handlers-bigtasks` working copy at 3,829 lines.
