# gppu.handlers

`gppu.handlers` reads files, folders, archives, Git history, native LLM session logs, and OpenAI or Anthropic export ZIP files through one typed handler interface.

## Calls

The same public call works synchronously when no event loop is running and is awaitable inside an event loop. Blocking file, archive, session, and Git work runs in a worker thread.

```python
records = file_handler.probe(path)
records = await file_handler.probe(path)

stats, session = session_handler(path)
stats, session = await session_handler(path)
```

`FileHandler.identify`, `probe`, `load`, `normalize`, `archive_path`, and `invalidate` use this behavior. `SessionHandler`, `ArchiveHandler`, and `GitHandler` identification and loading do too.

## LLM exports

`SessionHandler` recognizes OpenAI `conversations-NNN.json` members and Anthropic `conversations.json` inside ZIP files. It returns a `SessionFolder` containing one `SessionFile` per conversation. Each session keeps the ZIP in `location`, the JSON member in `path`, the provider ID in `uid`, and the original conversation object in `records`.

OpenAI turns follow the exported `current_node` chain. Anthropic turns follow the exported `chat_messages` order. A named conversation member with an unsupported shape raises an error.

## Git spans

`GitHandler` identifies the repository root and currently tracked files and folders. Their spans use commit timestamps from the local history reachable from the current `HEAD`; it never fetches or contacts an upstream. A tracked folder includes commits for historical paths beneath that folder, including files later deleted. Untracked paths retain normal file-system spans.

The handler reads the tracked paths and history once per repository state. Changes to `HEAD`, its ref, the index, the HEAD log, or packed refs invalidate that cached map. `.git` remains excluded from hierarchy listing and copying.
