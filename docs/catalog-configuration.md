---
fileClass: Document
created: 2026-09-21
updated: 2026-09-21
generated: { by: Codex/GPT-5, at: 2026-09-21 }
---

# Configuration-only Location lookup

`GppuCatalog()` reads the configuration already loaded by `Env`. Listing or looking up configured Locations does not construct a filesystem, access a provider, enumerate files, or refresh an index. A database loader can pass the same configuration as a mapping instead of changing the consumer API.

```python
from pathlib import Path
from gppu import Env
from gppu.handlers import GppuCatalog

Env.from_env(name='lake', app_path=Path('D:/Dev/CRAP/Projects'))
catalog = GppuCatalog()
locations = catalog.ls(recurse=True)
location = catalog.location('lake')
connection = catalog.connection('lake')
root = catalog.path('lake')
```

The application supplies its own configuration path. Importing gppu does not select a database, host catalog or filesystem.

## Input and operations

`connections` is a mapping keyed by connection UID. Existing gppu named `templates` resolve connection fields. `locations` is a nested list carrying `uid` values, or a mapping keyed by UID. Nested Locations inherit their enclosing connection. Their configured `path` is not appended to the parent's path: it already names the path within the provider. Existing `location_templates` are resolved with gppu's `TemplateSet`; data explicitly present on a Location remains literal.

`catalog.location(uid)` returns the resolved Location mapping. `catalog.connection(uid)` returns its configured connection without opening it. `catalog.path(uid, relative_path)` joins the Location's already-resolved absolute `access` root and a relative path; it refuses absolute input paths and parent traversal. A Location without local access is still listed, but requesting its local path fails.

The configuration loader supplies the execution-host `access` value. The catalog does not infer mounts, substitute a different host, or invent a local copy of an online Location.

`catalog.ls()` lists configured roots. `catalog.ls(uid)` lists configured child Locations. `recurse=True` descends configured Locations only. A Location with no configured children returns an empty list, regardless of the files it may contain. `info` and `ls` return fsspec-shaped rows with `name` equal to the Location UID and the Location properties in `gppu`. Both have synchronous `*_sync` counterparts. `refresh=True` is refused for configuration lookups; load updated configuration and construct a new catalog explicitly.

Files below a Location remain the separate `GppuFileSystem` surface. This change does not run indexing, alter handlers, change Record/Span storage, or change the external-index addressing protocol.

The pre-existing explicit directory argument, `GppuCatalog(absolute_catalog_folder)`, still selects the exported host-catalog implementation. It is not a fallback when configuration is absent or invalid.
