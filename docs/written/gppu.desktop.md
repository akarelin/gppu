<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/desktop.py e9f85372cf910d3b5985d71817edbb0dea67ed55 -->
`gppu.desktop` shows gppufs sources as one read-only Windows folder tree, mounted through fsspec's FUSE bridge. Each configured source is one named folder. Navigation and file bytes below it come from gppufs, and the module has no handler parsing and no index of its own.

## Classes and functions

`DesktopFileSystem` is an fsspec file system with the protocol `gppu-desktop`. It takes a dict that maps each folder name to a `GppuFileSystem`. The constructor rejects a name that is empty, `.` or `..`, that contains a slash, backslash or colon, or that is `Indexed`. It also rejects two names that are equal when compared case-insensitively. `ls`, `info` and `_open` take the first path segment, match it to a source name without regard to case, and join the rest onto that source's root. A path containing `..` raises `ValueError`. Any open other than `rb` raises `EROFS`.

`Indexed` is a virtual folder. Its contents are found when `Indexed` or a source folder is listed. The index files found are those in a source's root and in each of its first-level folders that no handler ignores. Each index opens as a `GppuIndexedFileSystem`. Its label is the source name, followed by ` › ` and the index name when the two differ. Discovered index files are left out of the source listings. A container that gppufs declares, such as an archive, shows as a directory with size zero. `close()` closes every index view.

`mount(sources, mount_point)` mounts a `DesktopFileSystem` in the current process and runs in the foreground. Its FUSE subclass refuses writes, creates, truncation, deletions, renames and permission or time changes with `EROFS`. It closes the file system when the mount is destroyed. WinFsp owns the Windows mount lifecycle. The FUSE bindings load only when `mount` runs, so the module imports without them.

## Using it

A program builds a dict of `GppuFileSystem` objects and passes it to `mount` with a mount point:

```python
from gppu.desktop import mount

mount({'Data': data_fs}, 'X:')   # data_fs is a GppuFileSystem built elsewhere; 'X:' is the mount point
```
