# Desktop filesystem

The Lake is browsable at `G:\Lake` through a read-only gppufs mount. Directory Opus, Explorer and file dialogs use the same Windows filesystem. The Start Menu has **gppufs** to browse the drive and **Mount gppufs** to start its process again after signing in. Startup at sign-in is not configured.

This is the working mount infrastructure. It currently mirrors the physical hierarchy with gppufs container handling. The requested index-based view that avoids deep folder navigation is still being defined and implemented; the physical mount alone does not complete that requirement.

Requirements: [SPEC_desktop.md](../SPEC_desktop.md). Configuration: [examples/desktop.yaml](../examples/desktop.yaml). The mount point is explicitly `G:`; the Lake source is `\\s1\Lake`. Each configured source appears as a named folder under the mount. Additional sources use that same mapping and are read by `GppuFileSystem`.

## Implementation

`gppu.desktop.DesktopFileSystem` projects the named source folders onto fsspec. Each listing and lookup calls gppufs; `gppu.is_container` makes archives browsable directories, including nested archives. Entry names come from gppufs's native path, preserving Unicode and literal URL punctuation. Reads call gppufs's `open`. The adapter has no metadata index or parsing of its own. gppufs continues to maintain its existing indexes beside sources; browsing does not change original file contents.

`mount` uses the upstream `fsspec.fuse.FUSEr` operations with fusepy and the official WinFsp driver. The mount is read-only at both WinFsp and operation levels. Its only open handles are those held by fsspec's bridge. It serves callbacks on one thread, matching gppufs's synchronous SQLite access. A failed callback is reported by fusepy on stderr and returned to Windows as an error.

Install the `desktop` extra for fusepy and install the official WinFsp driver on Windows. The existing shared virtual environment supplies Python. The launcher starts the mount process hidden; stdout and stderr are in `C:\.cache\gppufs-desktop`. Closing the process removes its drive; the launcher can start it again. The launcher does not install a service or modify Windows sign-in configuration.

Ordinary filesystem columns are exposed to desktop tools. Rich gppufs metadata remains in fsspec's `info` dictionaries; custom Directory Opus columns are not implemented. An archive is a directory in this view, so copying that directory copies its members rather than the original archive bytes.

## Verification

Native Windows enumeration of `G:\Lake` returned `_cruft`, `archive`, `Inbox`, `sources`, `text` and `timeseries`. Directory Opus's own `/info ...,list` returned the same folders with `display_path="G:\Lake"`. A native byte read through the mount matched its source on the Lake.

A separate temporary mount under `H:` proved nested ZIP navigation and reading a member named `Привет #100%.txt` using native Windows file calls. A native write was rejected with Windows error 19, media is write protected. That proof mount is removed after verification; its data is outside the Lake in `C:\.cache`.

Focused tests cover nested archive navigation, reads, write refusal, separate sources, case-insensitive source lookup, collisions and preserving unrelated copied indexes. The gppufs regression suite also passes.

Live SMB browsing revealed two index discovery defects, fixed in `GppuFileSystem`: SQLite read-only URIs require an empty authority for UNC paths; a copied index with a different folder inode is not evidence that this folder was renamed. Such an unrelated index is preserved rather than renamed or treated as an ambiguous match.

References: [fsspec FUSE bridge](https://filesystem-spec.readthedocs.io/en/latest/api.html#fsspec.fuse.run), [WinFsp](https://github.com/winfsp/winfsp), [Directory Opus external listing diagnostics](https://docs.dopus.com/doku.php?id=reference:dopusrt_reference:retrieving_file_and_folder_information).
