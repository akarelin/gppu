# gppu.handlers

`gppu.handlers` reads text files, folders, archives, Git history, native LLM session logs, and ChatGPT or Anthropic exports through one typed handler interface. `FileHandler` combines the domain handlers as mixins and resolves supplied paths with `gppu.full_path`.

## Calls

The same public call works synchronously when no event loop is running and is awaitable inside an event loop. Blocking file, archive, session, and Git work runs in a worker thread.

```python
records = file_handler.probe(path)
records = await file_handler.probe(path)

stats, session = session_handler(path)
stats, session = await session_handler(path)
```

`FileHandler.identify`, `probe`, `load`, `normalize`, `archive_path`, and `invalidate` use this behavior. `ChatGPTHandler`, `AnthropicHandler`, `MarkdownHandler`, `CSVHandler`, `LogHandler`, `SessionHandler`, `ArchiveHandler`, `GitHandler`, and `FolderHandler` identification and loading do too.

## Text files

`MarkdownHandler` recognizes `.md` files and returns a `MarkdownFile`. Its `frontmatter` dictionary retains every key and keeps date scalar spelling intact. `title` and `name` follow the declared `title|name` equivalence, then use the filename when neither exists. `tags` exposes the declared tag list. Its span covers `created` through `updated` when both values parse; datetimes without offsets use `America/Los_Angeles`.

`CSVHandler` recognizes `.csv` files and returns a `CSVFile` containing the complete header and data rows. `LogHandler` recognizes `.log` files, retains every row, and derives its span from absolute ISO 8601 timestamps at the beginnings of rows.

`ImageHandler` and `VideoHandler` reserve image and video EXIF metadata beside the structural recognition used by CRAP photo-indexer. They intentionally have no implementation and are not registered in `FileHandler`.

## LLM exports

`ChatGPTHandler` recognizes `conversations-NNN.json`, or the pair `chat.html` and `conversations.json`. `AnthropicHandler` recognizes `conversations.json` without `chat.html`. Both accept an extracted export folder or its ZIP archive and return a `SessionFolder` containing one `SessionFile` per conversation. `SessionHandler` is reserved for native JSONL logs.

OpenAI turns follow the exported `current_node` chain. Anthropic turns follow the exported `chat_messages` order. A named conversation member with an unsupported shape raises an error.

## RAR archives

`ArchiveHandler` identifies RAR 4 and RAR 5 signatures directly. It obtains member metadata from the installed RARLAB `rar` or `unrar` command. macOS and Debian resolve either command from `PATH`; Windows also checks the standard WinRAR installation directories. A missing command or failed listing is an error.

## Git spans

`GitHandler` identifies the repository root and currently tracked files and folders. Their spans use commit timestamps from the local history reachable from the current `HEAD`; it never fetches or contacts an upstream. A tracked folder includes commits for historical paths beneath that folder, including files later deleted. Untracked paths retain normal file-system spans.

The handler reads the tracked paths and history once per repository state. Changes to `HEAD`, its ref, the index, the HEAD log, or packed refs invalidate that cached map. `.git` remains excluded from hierarchy listing and copying.
