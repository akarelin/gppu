<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/handlers.py 62553764ec2596bacdb4c8e262e6f9838f300761 -->
`gppu.handlers` reads a file or a folder from its path and returns a record of what it is. Each handler reads one kind of data, and `probe` tells a program which handler to use for a path whose type it does not know in advance.

## How it works

`probe` reads nothing. From a path's stat and name, it returns a `Record` whose `type` and `subtype` name the handler that reads the path: a folder by its path, a file by its suffix. A link, a junction, an ignored path and an offline file come back as `fs_node` with their status as the subtype, and no handler reads them. `HANDLERS` maps each `(type, subtype)` pair to its handler class.

Each handler is a class of class methods. Its `parse(path)` returns the path's record with the handler's type and subtype added, plus whatever the handler reads. The records are Linked Data's shapes without the store, so handlers import neither Postgres nor `gppu.ld`. `Activity` adds a span of time, `Event` a `ts`, and `Session` a `uid`, the harness's own id for it.

The base `Handler` supplies the time helpers the others share: `time` reads a time from what a file writes, `valid_time` drops placeholder and future times, and `named` reads a span from a file's name.

`FolderHandler` counts the files, folders and bytes a folder directly holds, and its span comes from its files' times, not its subfolders'. `FileHandler` covers a file that no more specific handler reads. `SqliteHandler`, `MarkdownHandler`, `CSVHandler`, `LogHandler` and `EmailHandler` extend it: they read a SQLite file's tables and columns, a Markdown file's YAML frontmatter, a CSV file's header and row count with the span of its time columns, a log's first and last timed lines, and an email's time, subject, party and collision from its name. `SessionHandler` reads a harness's session `.jsonl` and identifies the harness from its messages, not its name; its `parse` returns a `Session`. `SessionFolderHandler` reads a harness's session folder and the sessions below it.

A read that fails raises. A handler reads the path it is given and nothing else: no index, no location, no fsspec.

## Usage

The module's own docstring shows the usual sequence: probe the path, look up its handler, then parse the path with it.

```python
record = probe('D:/Dev/gppu/README.md')
handler = HANDLERS[record.type, record.subtype]          # MarkdownHandler
record = handler.parse('D:/Dev/gppu/README.md')
```

A link, a junction, an offline file or an ignored path has no entry in `HANDLERS`, so the lookup fails for it.
