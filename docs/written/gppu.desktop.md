<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/desktop.py b8312f1f1c65a59ab75faf165b8a6072d0e33fc3 -->
`gppu.desktop` presents gppufs sources as a read-only Windows folder tree, mounted through fsspec's FUSE bridge. Each configured source appears as one named folder, and an `Indexed` folder lists the gppufs indexes found under those sources. The module adds no navigation, parsing, or index of its own. Every listing, metadata lookup, and byte read below a source goes to gppufs.

## How the parts work together

`DesktopFileSystem` is an fsspec filesystem with the protocol `gppu-desktop`. It takes a dict that maps each source name to a `GppuFileSystem`. Source names must be one Windows folder name, must be distinct when compared case-insensitively, and cannot be `Indexed`, which is reserved for the index view. A path is matched to a source case-insensitively. A path containing `..` raises `ValueError`. Archive containers that gppufs declares navigable appear as directories. Any open for writing raises `OSError` with `EROFS`.

The `Indexed` folder is discovered on demand. When a listing or lookup needs it, the module asks gppufs for the indexes under each source's root and its direct subfolders. Each index becomes a folder labelled with the source name, plus the subfolder name joined by ` › ` when it differs from the index name, and then the index's stem. Each label opens a `GppuIndexedFileSystem` view. Index files are left out of the source folders' listings. `close()` closes these views.

`mount()` is the only function that touches Windows. It wraps a `DesktopFileSystem` in a FUSE handler that refuses writes, creates, truncation, deletion, renames, and attribute changes with `EROFS`. It closes the filesystem when the mount is destroyed. It mounts read-only, in the calling process, in the foreground, under the volume name `gppufs`. WinFsp manages the mount lifecycle. The FUSE imports happen only inside `mount()`, so `DesktopFileSystem` can be used without them.

## Using it

Build each source as a `GppuFileSystem`, pass the dict to `mount()`, and give a drive letter or folder as the mount point:

```python
from gppu.desktop import mount

sources = {'Lake': lake}   # lake is a GppuFileSystem created elsewhere
mount(sources, 'L:')
```
