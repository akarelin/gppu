<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/desktop.py 5abc1942e0baae114b0d302e69a8228a0671dee6 -->
The `gppu.desktop` module presents gppufs sources as a read-only Windows folder tree, so a Windows desktop can browse the data lake and other locations that gppufs handles. It mounts that tree through fsspec's FUSE bridge. Navigation and file bytes below each source folder come from gppufs; the module contains no handler parsing and no index of its own.

## How the pieces work together

`DesktopFileSystem` is an fsspec filesystem that takes a dictionary of source names to `GppuFileSystem` roots and projects them into one namespace. Each name becomes a top-level folder. A name must be one Windows folder name, must differ from the other names ignoring case, and cannot be `Indexed`, which is reserved for the index view.

Beneath the source folders, the `Indexed` folder lists the gppufs index files found in each source root and in its subfolders. A subfolder that gppufs ignores, or that is a junction or link, is not entered. Each index appears under a label made from its source and its name, and is read through `GppuIndexedFileSystem`.

Archive files that gppufs declares as containers appear as folders. Other rows appear as files with their modification time in seconds. An archive member whose index row stores its time as text is left out, because Windows cannot be given that time. Listings fail with `ValueError` when two names collide ignoring case. Every write is refused with a read-only error.

`mount(sources, mount_point)` builds a `DesktopFileSystem` from the sources and runs it in the foreground in the current process through a read-only FUSE handler. That handler refuses write, create, delete, rename, and attribute changes, and closes the filesystem when the mount is destroyed. WinFsp owns the Windows mount lifecycle.

## Use

```python
from gppu.desktop import mount

# lake and inbox are GppuFileSystem instances, one per configured source
mount({'Lake': lake, 'Inbox': inbox}, 'X:')
```
