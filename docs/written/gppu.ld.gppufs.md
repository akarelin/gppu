<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/ld/gppufs.py eabac807d8d9e3e76a801e6a8194ff2fca2385f6 -->
`gppu.ld.gppufs` is gppu's `gppu.fs` on Linked Data. It reads the file locations from Linked Data's files API (`gppu.ld.files`), reaches each one only through that API at the address `connect()` is given, and keeps its files in gppufs's own index beside each location, not as Linked Data records.

## How the parts work together

`connect(url)` opens the one API connection that every other call uses, and raises `ValueError` for an empty address. `api()` makes a single request over that connection. A refused request raises `ValueError` with the API's reply, and a 404 raises `LookupError`.

`catalog()` builds a `GppuCatalog` from the locations in use. A location is included when it has a uid and a canonical URI, is not discarded, rejected or archived, and every location above it is also in use. Each location's connection is its root location's handler parameters. Providers are passed to `catalog()` by scheme. `FileSystem` handles `file://` URIs. `Drives` handles drive URIs on a Windows host's WSL: it maps a URI such as `file://alex-pc/D:/Dev` to the WSL mount named by the app's `drives` configuration, and raises if that setting is missing.

`here()` returns the folder on this host that a location's file URI names, or `None` if the URI names another host or is not a file URI. `reached()` collects every such folder that exists, checking each once, so a caller reads the result once and passes it on. `filesystem()` takes one location from the catalog and returns a `GppuFileSystem` for it, with its index in `.<location-name>.gppufs.sqlite` beside the folder. A listing reads the folder, and a lookup answers from the index. It raises `ValueError` when the location is not on this host.

## Use

Call `connect()` first, because `catalog()` makes its requests over that connection. Then pick a `uid` from the keys of `catalog.locations`.

```python
from gppu.ld import gppufs

gppufs.connect(url)
catalog = gppufs.catalog()
folders = gppufs.reached(catalog)
fs = gppufs.filesystem(catalog, uid, folders)
```
