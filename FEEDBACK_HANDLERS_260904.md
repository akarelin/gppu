# Feedback on the new handlers — 2026-09-04

Read of `gppu/handlers.py` on `handlers-bigtasks` (working copy, alex-pc) against the one application that already uses handlers: the lake's indexer, `D:\Dev\CRAP\Systems\Lake\indexer.py`.

## Three things stop the lake from using this today

**1. `FileHandler` no longer accepts handlers.** It is a mixin class with a fixed `handler_types` tuple and `FileHandler()` takes no arguments. Both callers pass instances:

```python
# D:\Dev\CRAP\Systems\Lake\indexer.py:66
HANDLERS = FileHandler(session_handler, archive_handler, _note_handler())
# D:\Dev\CRAP\Projects\textlake\handlers.py:115
file_handler = FileHandler(session_handler, archive_handler, note_handler)
```

The lake has its own handler — `NoteHandler`, markdown frontmatter — and it has no way in. It also needs to leave git out, and now cannot. The only route left is subclassing the private `_FileHandler`, which means every consumer reaches inside the module:

```python
class LakeHandler(_FileHandler, NoteHandler, SessionHandler, ArchiveHandler, FolderHandler):
    handler_types = (NoteHandler, SessionHandler, ArchiveHandler, FolderHandler)
```

`PLAN_HANDLERS_BIGTASKS.md` lists "Compose `FileHandler` from handler mixins without constructor injection" as intended, so this is a decision, not an oversight. It needs a supported way to compose a set — a public base, or `FileHandler.with_handlers(*types)` — otherwise every application depends on a private name.

**2. The module needs Python 3.14.** Five `except A, B:` clauses (PEP 758) — lines 1072, 1423, 2163, 2197, 2385. `pyproject.toml` declares `requires-python = ">=3.11"`. On 3.13 the import is a SyntaxError:

```
  File "D:\Dev\gppu\gppu\handlers.py", line 1072
    except OSError, UnicodeDecodeError:
SyntaxError: multiple exception types must be parenthesized
```

alex-pc's 3.13 carries gppu 2.50.6, so this is not theoretical. Either parenthesize them or raise `requires-python` to `>=3.14`.

**3. It is not released.** Installed gppu is 3.5.7 and its `handlers.py` is the old 24-line `Handler(load_object, derive_stats)`. Both lake modules fail to import right now:

```
ImportError: cannot import name 'FileHandler' from 'gppu.handlers'
```

## Performance

Identify-only walk of `D:\Dev\CRAP\Systems` — 524 entries, 470 files — measured on alex-pc, Python 3.14.7, warm page cache. No probing, no database.

| walk | time | per entry |
|---|---|---|
| `os.walk` | 0.002 s | 4 µs |
| session + archive + folder (what the lake configures today) | 0.684 s | 1,305 µs |
| new `FileHandler` default, all six | 4.283 s | 8,173 µs |

Per handler, same walk:

| handler | time | per entry |
|---|---|---|
| git | 4.087 s | 7,800 µs |
| session | 0.512 s | 977 µs |
| archive | 0.371 s | 709 µs |
| anthropic | 0.239 s | 457 µs |
| chatgpt | 0.218 s | 417 µs |
| folder | 0.179 s | 342 µs |

FileIndexer's measured alex-laptop pass was 68,192 files and 10,046 folders. At 1,305 µs that walk costs ~102 s of identification; at 8,173 µs it costs ~10.7 minutes. Across the lake's 1.7 M entities: ~37 minutes against ~3.9 hours.

**Git is six times everything else together, and it is in the default set.** `GitHandler.identify_sync` walks every parent looking for `.git`, then calls `_history`, which calls `_state` — reads `HEAD`, reads the branch ref, stats `index`, `logs/HEAD`, `packed-refs` — once per path examined. It also turns off both caches on purpose: `record()` re-runs identify for git on a cache hit, and `_probe_record` re-probes whenever git matched. Warm-cache probe of one tracked `.py` file is 1.21 ms with git in the set and 0.18 ms without.

Git spans are worth having. They belong on folders and on paths a caller asks for, not on every file the walk touches.

**Identification is content sniffing on every file, with no extension or size filter.** Measured on the same tree:

```
SessionHandler._head calls     940  = 2.00 per file
  of which repeat reads of the same file: 470
zipfile.is_zipfile calls       470  = 1.00 per file
```

Every file is opened and JSON-parsed twice. `SessionHandler.identify_sync` on a *folder* lists it and head-reads every file in it to decide whether the folder is a session folder; then the walk enters that folder and head-reads each file again for its own identify. `ArchiveHandler.identify_sync` adds `zipfile.is_zipfile`, then `rarfile.is_rarfile`, then a gzip check plus `tarfile.is_tarfile` — up to four more reads per file — for a `.py` or a `.jpg` as readily as for a `.zip`.

The lake pays all of it at `refresh` and `files`, the two levels that never probe anything. `ArchiveHandler.extensions` exists and identify does not consult it.

## Smaller things

- **`_head` reads a whole line.** `for line in stream` on a one-line 2 GB JSON file reads 2 GB into memory before the JSON check. The lake walks folders holding exports.
- **`SessionFile.records` keeps the entire parsed JSONL,** and `_probed` and `_session_cache` are unbounded. Probing a Sessions folder holds every parsed session at once. The lake works around this by calling `invalidate()` after every batch, which throws away the whole cache including the parts it still wants.
- **`_archive_children` scans the complete member tuple for each folder inside the archive** — members × folders. A RAR with 100k members and 10k folders is a billion comparisons.
- **`children()` drops `.git` silently.** The lake wants that folder as a row with `folder_class = '.git'`; it can never see it. Hiding it from copying is right; hiding it from listing removes the caller's choice.
- **`@sync` returns a Task inside a running loop.** `probe()` called from sync code that happens to sit inside an event loop returns a Task, not records. The `_sync` twins are the safe call and are the ones applications should use; the docs point at the decorated names.
- **`probe(path)` defaults to `recursive=True`** and materializes a Record for every descendant in a dict. On a Location root that is the whole tree in memory.
- **`Record.path` is `Path | PurePosixPath` and `location` is `str | Path | None`.** Every consumer writes `isinstance` checks to find out whether it is looking at a real file. A flag would carry it.

## What the lake would like handlers to carry

The lake re-stats files that `record()` has already stat'ed, because `Record` does not carry what it found:

- **Link and target.** `Record.is_folder` is False for a symlink to a directory, so the lake's indexer re-checks `is_junction()` and `is_symlink()` and reads `os.path.realpath`. `record()` already computed `is_symlink`.
- **Windows hidden and system attributes.** The lake calls `stat(follow_symlinks=False)` a second time for `st_file_attributes`.
- **A cheap identify.** Extension first, content only when the extension says it might be worth it, or a way to ask for identification without sniffing at all. This is the whole difference between a 37-minute walk and a 4-hour one.

## Measurements

Scripts are in this session's scratchpad; each is ~30 lines and re-runnable:
`bench2.py` (per-handler walk timing), `heads.py` (head-read and zip-sniff counts).

Host alex-pc, `D:\Dev\gppu\.venv` (Python 3.14.7), `handlers-bigtasks` working copy as of 2026-09-04.
