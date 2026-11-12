<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/fs_index.py 5d9d4aa6afbd9e1223d640059456d3b461415185 -->
`gppu.fs_index` reads an existing gppufs SQLite index as a flat, read-only fsspec filesystem. The index is the source of the listing, including for a copied or synced index, and original relative paths are kept so that bytes can still be read.

## Classes and functions

`GppuIndexedFileSystem` opens an index file read-only and lists every file the index holds under one flat root. Each file appears under a display name: its last path part, or, where two names collide ignoring case, the full path joined with ` › `. If the names still collide on Windows, opening raises `ValueError`. Files whose handlers are ignored, and gppufs's own `.gppufs.sqlite`, `-wal` and `-shm` files, are not listed. Archive members, stored with `::`, are named by the archive's names followed by the member's.

`info` and `ls` answer from the index's rows and never run a handler. Byte reads depend on the index's name. An index whose name starts with a dot sits beside its data, so its folder is the data root and reads go to the original files, including archive members. Any other name marks a provenance-named snapshot. A snapshot can be listed, but reading its bytes raises `FileNotFoundError`, because no original source is bound. The filesystem accepts only `rb` mode and raises `PermissionError` for any other. Call `close` to release the database connection.

The display names are cached and rebuilt only when the index file's modified time or size changes.

`indexes(files, folder)` is the companion function. Given a `GppuFileSystem` and a folder, it yields the `.gppufs.sqlite` files directly in that folder. It yields nothing for a folder the account cannot list. Pass each result to `GppuIndexedFileSystem` to open it.

## Use

```python
from pathlib import Path
from gppu.fs_index import GppuIndexedFileSystem

fs = GppuIndexedFileSystem(Path('Data/.Data.gppufs.sqlite'))
print(fs.ls('/', detail=False))
fs.close()
```
