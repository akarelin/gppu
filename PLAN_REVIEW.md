---
fileClass: Document
created: 2026-10-19
updated: 2026-10-19
generated: { by: claude-code/opus-5-5, at: 2026-10-19T09:45 }
---

# gppu review

Goal: gppu's real functionality, which predates Linked Data and was developed over years, separated from what models added unasked, with one implementation of each thing, documented from its code. Nothing that works is dropped; the Linked Data specification is bridged to gppu, not gppu rewritten to it.

Alex, 2026-10-19: "it doesn't mean you have to rewrite GPPU ... I don't want to destroy the working functionality, yet the documentation specifically describes the opposite product." "GPP has like 7 different implementations of things related to linked data. I found like 5 different environment implementations. You gotta clean this up." "How to extract the real functionality that I needed has been there, has been painstakingly developed from slop. I don't know. Start somehow."

## Documentation
- VS Code resolves gppu from `~/.venv` (editable install in compat mode): done
- Every module of gppu in the docs, not only `gppu.ld`: done, published at kb.karel.in/gppu/v3/
- Every class of gppu in one diagram (pyreverse): done, `classes.html`
- graphify of today's gppu, code only: not started

## Inventory: in progress
Each implementation of the same thing, where it is, and since when. Who asked for it is not read from git: every commit is under Alex's name.

Configuration and environment:
- `Env` (`gppu/gppu.py`): class-level configuration, `from_env`, `glob`, `glob_dict`; gppu.py since 2023-03-31.
- `mixin_Config`, `_Config` (`gppu/gppu.py`): an object's own section, `my()`.
- `Vault` and `VaultProvider*` (`gppu/gppu.py`): secrets from the environment or Azure Key Vault.
- `_Environment`, `_Rules`, `_State` (`gppu/environment.py`, 2026-09-16): platform and host, tables, macros and rows built from the configuration, over `Env.from_env`.
- `params.py` (2026-09-25): `main`'s parameters from the command line, then the configuration, then the signature.
- `GppuCatalog` (`gppu/fs.py`): reads its own YAML (`locations.yaml`, sources, replicas) beside `Env`.
- `_MqttConfig` (`gppu/iot.py`): MQTT's configuration as an app.

Postgres:
- `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy) in `gppu/data.py`, and `gppu.ld`'s own async SQLAlchemy engine over psycopg 3 (`connect()`), which uses neither.

Linked Data and its parts:
- `Span`, `TimeSpan` (`gppu/gppu.py`) and a second `Span` in `gppu/ld/__init__.py`, which says it is not gppu's.
- `Record` in `gppu/fs.py` and `Record`, `Node`, `Link` in `gppu/ld/__init__.py`.
- `Location`, `Container`, `Collection`, `GppuIndex`, `GppuCatalog` in `gppu/fs.py` (8,287 lines).
- `gppu/fs-dumpoftext.py` (2026-09-24): another `Container`, `Location`, `Collection`, `Index`, `SqliteIndex`; its name is no module's, so nothing imports it.
- `gppu/ld/files.py` (2026-10-18): files and locations as Linked Data records, `File`, `Entry`, `Configured`, `Addressed`, beside gppufs.
- `gppu/ld/annotations.py` (2026-10-18): `Annotation`, a type the specification does not have.
- RAN `Projects/ld/gppufs`: gppufs's `GppuIndex` over the files API, outside gppu.

## Independent, not scoped
- Bridge the Linked Data specification to gppu
- APIApp

## Found, not this task
- GitHub Pages is not enabled for gppu, so `gppu-docs.yaml`'s last step fails.
- kb.karel.in/obsidian/ answers 502: `kb-web` was suspended 2026-09-21 and nothing serves 127.0.0.1:8086 on trix.
