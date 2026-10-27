# Desktop filesystem

The Lake is browsable at `G:\Lake` through a read-only gppufs mount. Directory Opus, Explorer and file dialogs use the same Windows filesystem. The Start Menu has **gppufs** to browse the drive and **Mount gppufs** to start its process again after signing in. Startup at sign-in is not configured.

`G:\Lake` provides physical navigation with gppufs containers. `G:\Indexed` provides a separate view of the existing gppufs indexes. Within each indexed location, stored files appear directly, including files recorded many folders below its root. Directory Opus is open at `G:\Indexed\Lake` for Alex's acceptance; verification of the implementation does not substitute for that acceptance.

Requirements: [SPEC_desktop.md](../SPEC_desktop.md). Configuration: [examples/desktop.yaml](../examples/desktop.yaml). The mount point is explicitly `G:`; the Lake source is `\\s1\Lake`. Each configured source appears as a named folder under the mount. Additional sources use that same mapping and are read by `GppuFileSystem`.

## Implementation

`gppu.fs.desktop.DesktopFileSystem` projects the named source folders onto fsspec. Each listing and lookup calls gppufs; `gppu.is_container` makes archives browsable directories, including nested archives. Entry names come from gppufs's native path, preserving Unicode and literal URL punctuation. Reads call gppufs's `open`. The adapter has no metadata index or parsing of its own. gppufs continues to maintain its existing indexes beside sources; browsing does not change original file contents.

`mount` uses the upstream `fsspec.fuse.FUSEr` operations with fusepy and the official WinFsp driver. The mount is read-only at both WinFsp and operation levels. Its only open handles are those held by fsspec's bridge. It serves callbacks on one thread, matching gppufs's synchronous SQLite access. A failed callback is reported by fusepy on stderr and returned to Windows as an error.

## Indexed navigation

`gppu.fs.fs_index.GppuIndexedFileSystem` reads the actual `gppufs_entries` table through a read-only SQLite connection. It lists entries recorded as files without enumerating their physical parents or reparsing their content. The connection is reused while the view exists. Display names map to original relative paths; metadata remains in SQLite. Unique names appear as filenames; collisions include original parent names separated by ` › `, and a remaining Windows name collision is reported as an error. Reads of colocated indexes go through gppufs to the original relative path, including archive members.

Index discovery examines the source root and its immediate folders, and the physical folder currently being browsed. It does not crawl the share. A deeper index becomes available when its folder is visited; its indexed descendants then require no further physical traversal. Recognized gppufs index files become folders under `Indexed` and are omitted from the physical listing. Additional sources use the same configured `sources` mapping.

A dotted colocated index can be used after its containing folder has moved or synced: this view neither changes its filename nor depends on matching another host's inode. A provenance-named snapshot can list its records, but has no automatically bound original content source. Missing original content raises a file-not-found error; it never substitutes a file with the same name beside the snapshot. The old TextLake index contains stale entries, so its listing does not prove those source files remain present. Historical non-gppufs databases retain their ordinary file representation.

Install the `desktop` extra for fusepy and install the official WinFsp driver on Windows. The existing shared virtual environment supplies Python. The launcher starts the mount process hidden; stdout and stderr are in `C:\.cache\gppufs-desktop`. Closing the process removes its drive; the launcher can start it again. The launcher does not install a service or modify Windows sign-in configuration.

Ordinary filesystem columns are exposed to desktop tools. Rich gppufs metadata remains in fsspec's `info` dictionaries; custom Directory Opus columns are not implemented. An archive is a directory in this view, so copying that directory copies its members rather than the original archive bytes.

## Verification

Native Windows enumeration of `G:\Lake` returned `_cruft`, `archive`, `Inbox`, `sources`, `text` and `timeseries`. Directory Opus's own `/info ...,list` returned the same folders with `display_path="G:\Lake"`. A native byte read through the mount matched its source on the Lake.

The live indexed view lists `note-000-auto_sum_note.md` directly under `G:\Indexed\Lake`, while the original remains beneath `sources/2026/recordings/plaud/09/01/0c7bf17355bb177d62dea7dc8986c79e`. A Windows read through that indexed name matched the original bytes. The original folder was listed through gppufs to populate its genuine metadata index; no demonstration records or duplicate source files were created. Directory Opus's actual window was inspected and refreshed after the mount update; the indexed files were visible there.

A separate temporary mount under `H:` proved nested ZIP navigation and reading a member named `Привет #100%.txt` using native Windows file calls. A native write was rejected with Windows error 19, media is write protected. That proof mount is removed after verification; its data is outside the Lake in `C:\.cache`.

Focused tests cover nested archive navigation, reads, write refusal, separate sources, case-insensitive source lookup, collisions, preserving unrelated copied indexes, flat access to deep files, synced indexes with unavailable originals, and refusing unrelated content beside transported snapshots. The gppufs regression suite also passes.

Live SMB browsing revealed two index discovery defects, fixed in `GppuFileSystem`: SQLite read-only URIs require an empty authority for UNC paths; a copied index with a different folder inode is not evidence that this folder was renamed. Such an unrelated index is preserved rather than renamed or treated as an ambiguous match.

References: [fsspec FUSE bridge](https://filesystem-spec.readthedocs.io/en/latest/api.html#fsspec.fuse.run), [WinFsp](https://github.com/winfsp/winfsp), [Directory Opus external listing diagnostics](https://docs.dopus.com/doku.php?id=reference:dopusrt_reference:retrieving_file_and_folder_information).
