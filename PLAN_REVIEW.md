---
fileClass: Document
created: 2026-10-19
updated: 2026-10-19
generated: { by: claude-code/opus-5-5, at: 2026-10-19T10:55 }
---

# gppu review

Goal: gppu does what it is meant to. gppufs and Linked Data are native to gppu, built on gppu's own configuration, logging, apps and primitives; each thing has one implementation; the documentation is generated from gppu's code alone. Nothing that works is dropped; backwards compatibility is not a constraint.

Alex's requirements (2026-10-18, deciding where Linked Data lives): Linked Data is a submodule of gppu, its base API for records in gppu; the locations API gppu already has serves it; it uses the primitives gppu already has, such as spans and paths; gppu's Postgres and ORM are improved, its unused ORM replaced by the one Linked Data uses; an API app is a type of gppu app. (2026-10-19): gppu is not rewritten and what works is kept; documentation is generated correctly; functionality spread over several files is put right; gppufs and Linked Data are native to gppu, not side modules that do not use it.

## Plan
1. Documentation from gppu's code: done. kb.karel.in/gppu/v3/: every module's reference, also what has no docstring; the package's exports on the home page; graph.html, graphify's graph grouped by gppu's modules, read without a model. It shows gppu from before the rebuild landed, and is republished once Alex decides whether the rebuild stays.
2. One Span: done. gppu's `TimeSpan` holds an open end, its bounds and the specification's forms; `gppu.ld.Span` is that `TimeSpan` with Linked Data's reading rules (gppu daf7b13).
3. One ORM: done. `gppu.data._SQABase`, which nothing used, is the ORM `gppu.ld` uses, and `gppu.ld.connect()` opens its store through `gppu.data.async_engine`; `_PGBase` is unchanged, since CCTV-detective, admin_ui, Plaud and CRAP's file_indexer use it (gppu d2d1e27).
4. gppufs on Linked Data inside gppu: done, one difference open (below).
5. APIApp: done. `gppu.app.APIApp` is the AsyncApp that serves HTTP on uvicorn at its configuration's host and port: its own objects at `/rest` and each ASGI app its `apis()` gives at its path (gppu 6a36245). RAN `Projects/ld/api.py` is an APIApp serving Linked Data at `/ld/v1` (RAN 592adca5e). gppufs's `/config` and `/lake` are a FastAPI app, `gppu.fs.api(lake)`, which an APIApp serves among its apis, in place of `serve()`'s own `ThreadingHTTPServer` (gppu 86c9b53).
6. One environment: done. `Environment` takes os, user and home from `Env`, which detects them once, and names its platform from `Env.os`; `params` reads the configuration with `deepget` instead of its own copy; `deepget` returns a falsy value at a nested path, where a nested `false` used to come back as the default; `detect_os` knows macOS (gppu d0f192a). The rest are layers over `Env`, not copies of it: `_Config` is an object's section, `Vault` its secrets, `_MqttConfig` a source that loads into `Env`, `GppuCatalog` reads `Env` unless given a mapping or an exported catalog folder.
7. `fs-dumpoftext.py` to `archive/`: done (gppu 6d75c1e).
8. No hard code in gppu: in progress.

## 8. No hard code in gppu
- Done: `gppu.fs` read an offset-free time in a Pacific zone of its own; it uses gppu's `MY_TZ` (gppu 483dc05).
- Done, by LD-Streamline's rebuild: `gppu.ld`'s every-record statuses are the specification's six (`new`, `active`, `pending`, `discarded`, `rejected`, `archived`) and its type codes the specification's twenty; `Activity`'s run phases, `annotation` and the twice-defined `FOLDERS` and `DELETED` are gone. The record search's example filter is on `discarded`, not `abandoned` (gppu f3966fb).
- Configuration copied into code: `IgnoredHandler`'s `IGNORED_NAME_PATTERNS` and `IGNORED_FOLDER_PATTERNS` and `_IndexHandlers`'s `FOLDER_CLASSES` in `gppu/fs.py` are CRAP `_config/file_indexer/file_indexer.yaml`'s `global_exclusions/patterns` and `folder_classes`, without its `monero-gui-*`. They add preservator's `$RECYCLE.BIN` and `System Volume Information`, and `OneDriveTemp`, `Cache`, `.cache` and `.SynologyWorking Directory`, which no configuration has. No program in use loads those sections: CRAP's configuration tree has none, nor has RAN FileIndexer's `gppufs.yaml`.
- Open: where gppufs's ignore rules live, so every program that walks files reads them from configuration.
- Kept, Alex's own: `MY_TZ` (Pacific), the `C:\.cache` rule (`gppu.fs.CACHE`), `chrome.py`'s Chrome paths.

## 4. gppufs on Linked Data inside gppu
- Done: RAN `Projects/ld/gppufs` is `gppu.ld.gppufs`, gppufs's catalog, Lake and index kept by Linked Data's files API; FileIndexer gives it the API's address from its own `gppufs.yaml` (gppu ab3707c, RAN b656547eb and bcb6abc3a). RAN's five checks pass on it, and FileIndexer reads its 175 locations through it.
- Done: one rule for an address below a location's canonical uri and for reading one back, `gppu.fs`'s `_address` and `_below`; `LocationHandler.located`, `GppuFileSystem._located` and `_address_of`, `gppu.ld.files`'s `address()` and `below()` and `gppu.ld.gppufs` use it in place of their own copies. Every address is as it was, except under `file:///`, which gave `file:/home` (gppu e63fee0).
- Done: `Location.uri_of` keeps a canonical uri's trailing slash as the canonical uri's own, so a file below `file:///D:/` is `file:///D:/Contacts/person.json`, not `.../person.json/`; none of CRAP FileIndexer's records had an address ending in `/`. Linked Data's `address()` is `uri_of`'s rule (gppu 4f2caa6).
- Open: gppu writes a name in an address two ways. `Location.uri_of` escapes each name (`a%20b`), and CRAP FileIndexer's records and Linked Data's addresses have it so. The gppufs index rows `LocationHandler` writes have names as they are (`a b`), and `GppuFileSystem` reads addresses back that way. Making them one changes the rows one of the two already holds.
- Done: files are in gppufs's own index beside each location, as the specification keeps them, and Linked Data holds the locations. LD-Streamline's rebuild of `gppu.ld.files` gives the locations in use at `GET /files/locations`; `gppu.ld.gppufs` makes gppufs's catalog from them and keeps the Collection's writes (a new location an `fs_location`) and `filesystem()`; RAN's FileIndexer indexes into each location's own gppufs index and its TUI reads from it; `GppuFileSystem.stored()` reads an index without touching the disk. FileIndexer's `runs` and `queue` refuse, since runs have no type (Alex).
- On master before Alex's review: the process that commits on its own merged both changes into the D:\Dev checkouts and pushed gppu and RAN to GitHub at 13:44. Alex decides whether they stay. The five checks pass on D:\Dev master, the new `check_fileindexer.py` among them, and so do gppu's tests. Patches in `D:\Work\10\19\gppu-review`.
- Open: `gppu.fs.api`'s `/lake` reads through its own host's Provider, so it cannot read another host's files or indexes, and its folder listing has no paging. The gppufs note leaves open which index answers a lookup and how a question across locations is answered.

## Done before the plan
- VS Code resolves gppu from `~/.venv`: gppu installed editable in compat mode.
- `gppu.fs`: the type of an archive's members names `collections.abc.Collection`, since gppu.fs's own `Collection` took the name; the handler reference regenerated.

## Inventory
Configuration and environment:
- `Env` (`gppu/gppu.py`): class-level configuration, `from_env`, `glob`, `glob_dict`.
- `mixin_Config`, `_Config` (`gppu/gppu.py`): an object's own section, `my()`.
- `Vault` and `VaultProvider*` (`gppu/gppu.py`): secrets from the environment or Azure Key Vault.
- `_Environment`, `_Rules`, `_State` (`gppu/environment.py`): platform and host, tables, macros and rows built from the configuration, over `Env.from_env`.
- `params.py`: `main`'s parameters from the command line, then the configuration, then the signature.
- `GppuCatalog` (`gppu/fs.py`): reads its own YAML (`locations.yaml`, sources, replicas) beside `Env`.
- `_MqttConfig` (`gppu/iot.py`): MQTT's configuration as an app.

HTTP:
- `mixin_Rest` (`gppu/app.py`), which `AsyncApp` includes: every public member of an app over HTTP; `APIApp` is its listener.
- `gppu.fs.api`: gppufs's `/config` and `/lake` as a FastAPI app; `gppu.fs.serve` runs it alone on uvicorn.
- `gppu.ld`'s FastAPI apps (`api_at`, `served`), which RAN `Projects/ld/api.py` serves as an `APIApp`.

Linked Data and its parts:
- `Record` in `gppu/fs.py` and `Record`, `Node`, `Link` in `gppu/ld/__init__.py`.
- `gppu/ld/files.py`: the file system types at `/files` and the locations in use at `/files/locations`; `gppu/ld/gppufs.py`: gppufs's catalog made from them. `Annotation`, a type the specification does not have, is in `archive/gppu/ld/annotations.py`.

## Found, not this task
- GitHub Pages is not enabled for gppu, so `gppu-docs.yaml`'s last step fails.
- kb.karel.in/obsidian/ answers 502: `kb-web` was suspended 2026-09-21 and nothing serves 127.0.0.1:8086 on trix.
- The `ld` image has no `textual`, so `check_fileindexer.py`'s TUI part fails in it unless installed.
- Something in the RAN checkout commits staged changes on its own, with generic messages (b656547eb, bcb6abc3a); the gppu checkout too (4f2caa6), and a clone under `C:\.cache` once its files were open in VS Code. On 2026-10-19 at 13:44 it merged two such clones into the D:\Dev checkouts' master and pushed gppu and RAN to GitHub.
- CRAP's admin_ui runs its own HTTP server rather than an `APIApp`.
- RAN `Projects/ld/work.py:152` builds a `Span` from a value that is not one.
- `Env.glob` answers a default for a missing key and `Environment.glob` raises; both read `Env.data` with `deepget`.
