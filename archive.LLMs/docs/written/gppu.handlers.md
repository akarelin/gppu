<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/handlers.py bb09c8a9f85c6097993c35738282e7e660f7b2f7 -->
`gppu.handlers` reads what a file or a folder is and holds, and returns it as a record. It has one handler for each kind of data, so a program can ask about any path without knowing its type in advance.

`probe` comes first. It is gppu's `probe_path` returned as a `Record`. From the path's stat and name, with nothing read, it gives a type and subtype, and those name the handler that reads the path. A link, a junction, an ignored path and an offline file get type `fs_node` with a status as subtype, and no handler reads them.

## Handlers and how they fit together

Every handler subclasses `Handler`, a class of class methods with no instances. Its `parse(path)` reads the path and returns a `Record`, the shape of Linked Data's record without its store. A handler's subtype is its class name without `Handler`, in lower case, unless the class sets its own. Each subtype's `parse` adds to the `parse` of its type.

`Handler` also provides the shared time reading. `time` turns a value a file writes into a datetime. `valid_time` refuses placeholder times and times in the future. `spanning` gives the span from the earliest to the latest of a set of times. `named` reads the span a file or folder name says.

The handlers are:

- `FolderHandler` counts a folder's direct files, folders and bytes, leaving out what `probe` marks as ignored.
- `FileHandler` is the generic file, read only by its stat.
- `SqliteHandler` lists tables and their columns. It opens the file read-only and reads no rows.
- `MarkdownHandler` reads YAML frontmatter, not the body.
- `CSVHandler` reads the header, the row count and the span of the time columns.
- `LogHandler` finds the first and last timed lines, reading from both ends of the file.
- `EmailHandler` reads the time, subject and party from a `.msg` or `.eml` name. It does not open the message.
- `SessionHandler` reads a native `.jsonl` session. It tells the harness (Codex, Claude Code, Gemini CLI, OpenClaw, Agy or Hermes) from the messages, not the name, and returns a `Session`.
- `ExportHandler` reads ChatGPT and Anthropic conversation exports, returning one `Session` per conversation.
- `SessionFolderHandler` walks a harness's session folder and reads the sessions beneath it.

`HANDLERS` maps each `(type, subtype)` pair to its handler, so the record from `probe` finds its handler. A handler reads the path it is given and nothing else: no index, no location, no fsspec. A read that fails raises.

## Usage

A program probes a path, looks up the handler for the record's type and subtype, and parses the path with it:

```python
record = probe('D:/Dev/gppu/README.md')
handler = HANDLERS[record.type, record.subtype]          # MarkdownHandler
record = handler.parse('D:/Dev/gppu/README.md')
```
