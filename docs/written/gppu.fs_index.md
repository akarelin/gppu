<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/fs_index.py 24b97ff3d71aa42ba27311a90d605597a952e94e -->
Reads an existing gppufs SQLite index as a flat, read-only fsspec filesystem. The index is the source of the listing, including for a copied or synced index, and original relative paths are kept so bytes can still be read. The index file is never renamed or written.

`GppuIndexedFileSystem` is the filesystem. It opens the index read-only and checks that it has the `gppufs_entries` table. `ls` lists the index's files at the root, each with metadata from its index row, and `info` returns the same for one name. The root is a directory. A name is the last part of an indexed path. When two names collide ignoring case, each takes its full path, joined with ` › `. If those still collide on Windows, listing raises `ValueError`. Files the handlers call ignored, and gppufs's own `.gppufs.sqlite` files, are not listed. Instances are not reused by fsspec's instance cache.

Reading bytes needs an original source. An index whose name starts with `.` is colocated: the folder it sits in is the source. A snapshot with a provenance name has no source, so reading its files raises `FileNotFoundError`. Only the `rb` mode is accepted; any other mode raises `PermissionError`. A member of an archive has a path containing `::`. It is read from its archive in the source and returned whole, in memory.

`indexes(files, folder)` is a generator. It yields the path of each `.gppufs.sqlite` file directly in `folder`, and yields nothing when the folder cannot be listed. It does not check the tables; opening the index with `GppuIndexedFileSystem` does that.

```python
from gppu.fs_index import GppuIndexedFileSystem

fs = GppuIndexedFileSystem(index)  # index: a str or Path to a .gppufs.sqlite file
for name in fs.ls('/', detail=False):  # names start with '/'
    print(fs.info(name))
fs.close()
```
