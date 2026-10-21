<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/desktop.py eb3b8814d42c380c3a76746746e417a37628cb85 -->
## Purpose

`gppu.desktop` presents gppufs sources as ordinary folders in Windows, so Explorer and other desktop programs can browse them. The view is read-only. It holds no handler parsing or index: navigation and file bytes below each source folder come from gppufs.

## Classes and functions

`DesktopFileSystem` is an fsspec filesystem that combines several named gppufs roots into one namespace. It takes a dict that maps a folder name to a `GppuFileSystem`. Each name must be a single Windows folder name, must not be `Indexed` in any letter case, and must be unique when compared case-insensitively. An empty dict also raises `ValueError`.

Each source appears as a top-level folder. A subfolder that holds a gppufs index file is listed as an index view instead of a plain folder, and the index file itself is hidden from the source listing. Index views are gathered under a top-level `Indexed` folder and labelled with the source and subfolder name. Each is opened as a `GppuIndexedFileSystem`, and `close()` releases them. Discovery runs as folders are listed, so an index appears when its folder is first browsed.

An archive that gppufs declares as a container appears as a directory with size 0, even though fsspec sees it as a file. A path containing `..` raises `ValueError`. A name that matches no source or index view raises `FileNotFoundError`.

Writing is refused. Opening anything in a mode other than `rb` raises `OSError` with `EROFS`. The FUSE layer returns the same error for create, write, rename, delete and similar operations.

`mount()` is the only function. It imports the FUSE bridge when called, then runs the mount in the current process, in the foreground, read-only, under the volume name `gppufs`. WinFsp owns the Windows mount lifecycle. Each released file handle is closed, and when the mount is destroyed the filesystem closes its index views.

## Usage

```python
from gppu.desktop import mount

mount({'Lake': lake}, mount_point)
```

Here `lake` is a `GppuFileSystem`, and `mount_point` is where the view appears. The call blocks while the mount is up.
