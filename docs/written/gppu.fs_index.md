<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/fs_index.py e76c0537f2fc1ae1b34f49c15c45df5c65ca8141 -->
`gppu.fs_index` reads an existing gppufs SQLite index as a flat, read-only fsspec filesystem. The listing comes from the index itself, so a copied or synced index shows the same files. Byte reads go to the original files by their stored relative paths, and the index is never renamed.

`GppuIndexedFileSystem` is the filesystem. On construction it opens the index read-only and checks that it has the `gppufs_entries` table. Its `info()` and `ls()` answer from the metadata JSON that the index stores for each file. Only files are listed, with no subdirectories. The root listing shows each file by its bare name. When two files share a name, ignoring case, each is shown by its path joined with ` › `. Two names that still collide on Windows raise `ValueError`, and so does any stored path that is absolute or contains `..`. Index files named `*.gppufs.sqlite` and their WAL and shared-memory files are left out of the listing.

Reading bytes needs a source. An index whose name starts with a dot is colocated, and the filesystem binds it to a `GppuFileSystem` rooted at the index's folder. Any other index is a snapshot with no bound source, so opening one of its files raises `FileNotFoundError`. Opening is read-only: any mode other than `'rb'` raises `PermissionError`.

`indexes(files, folder)` is the companion function. It yields the path of each index file directly in `folder`, found through a `GppuFileSystem`. It does not open them. Each one is checked when it is passed to `GppuIndexedFileSystem`.

A program lists one folder's indexes and reads a file from one of them like this:

```python
from gppu.fs import GppuFileSystem
from gppu.fs_index import GppuIndexedFileSystem, indexes

files = GppuFileSystem(root)
for index in indexes(files, folder):
    view = GppuIndexedFileSystem(index)
    print(view.ls('', detail=False))
    view.close()
```
