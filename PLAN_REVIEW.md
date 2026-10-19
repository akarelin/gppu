---
fileClass: Document
created: 2026-10-19
updated: 2026-10-19
generated: { by: claude-code/opus-5-5, at: 2026-10-19T10:20 }
---

# gppu review

Goal: gppu does what it is meant to: one implementation of each thing, Linked Data a submodule of gppu built on gppu's own primitives, and documentation generated from gppu's code alone. Nothing that works is dropped.

Alex, 2026-10-18, deciding Linked Data's place: "we put the whole uh, REST, uh, the whole like base API for records in GPPU. I believe that there's locations API already in GPPU and might as well be there. ... some of the primitives uh, of what kind of a data, uh, like spans, like path, all of those are already in GPU. So, okay, let's decide it. So linked data becomes a new submodule of GPU. ... you can improve uh, Postgres and uh, uh, current ORM implementation of GPP. I, I don't think it's really being used. So maybe uh, maybe replace it with uh, the ORM that you use." Same day: "you can have an API app, and GPPU is another type of app".

Alex, 2026-10-19: "it doesn't mean you have to rewrite GPPU ... I don't want to destroy the working functionality". "start off with two things: correctly generate documentation, and do GPP what needs to be done ... there are a bunch of files where functionality is spread, and it's just wrong. So make GPPU work correct."

## Plan
1. Documentation from gppu's code: done. kb.karel.in/gppu/v3/: every module's reference, every class and function also without a docstring, the package's exports on the home page, and graph.html, graphify's graph grouped by gppu's modules (no model, no Mermaid).
2. One Span: in progress.
3. One Postgres and ORM: not started.
4. One locations API: not started.
5. APIApp: not started.
6. One environment: not started.
7. `fs-dumpoftext.py` to `archive/`: not started.

## 2. One Span
gppu has `Span` and `TimeSpan` in `gppu/gppu.py`, used by gppufs (`gppu/fs.py`, about twenty places). `gppu.ld` has its own `Span`, a pydantic model with `bounds`, open ends and the specification's forms (start and end; date and duration; date; ts), used by `gppu.ld.files` and RAN `Projects/ld` (`sessions.py`, `work.py`).

## Done before the plan
- VS Code resolves gppu from `~/.venv`: gppu installed editable in compat mode.
- `gppu.fs`: the type of an archive's members names `collections.abc.Collection`, since gppu.fs's own `Collection` took the name.

## Inventory
Configuration and environment:
- `Env` (`gppu/gppu.py`): class-level configuration, `from_env`, `glob`, `glob_dict`.
- `mixin_Config`, `_Config` (`gppu/gppu.py`): an object's own section, `my()`.
- `Vault` and `VaultProvider*` (`gppu/gppu.py`): secrets from the environment or Azure Key Vault.
- `_Environment`, `_Rules`, `_State` (`gppu/environment.py`): platform and host, tables, macros and rows built from the configuration, over `Env.from_env`.
- `params.py`: `main`'s parameters from the command line, then the configuration, then the signature.
- `GppuCatalog` (`gppu/fs.py`): reads its own YAML (`locations.yaml`, sources, replicas) beside `Env`.
- `_MqttConfig` (`gppu/iot.py`): MQTT's configuration as an app.

Postgres:
- `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy) in `gppu/data.py`, and `gppu.ld`'s own async SQLAlchemy engine over psycopg 3 (`connect()`), which uses neither.

Linked Data and its parts:
- `Record` in `gppu/fs.py` and `Record`, `Node`, `Link` in `gppu/ld/__init__.py`.
- `Location`, `Container`, `Collection`, `GppuIndex`, `GppuCatalog` in `gppu/fs.py`.
- `gppu/fs-dumpoftext.py`: another `Container`, `Location`, `Collection`, `Index`, `SqliteIndex`; nothing imports it.
- `gppu/ld/files.py`: files and locations as Linked Data records beside gppufs.
- `gppu/ld/annotations.py`: `Annotation`, a type the specification does not have.
- RAN `Projects/ld/gppufs`: gppufs's `GppuIndex` over the files API, outside gppu.

## Found, not this task
- GitHub Pages is not enabled for gppu, so `gppu-docs.yaml`'s last step fails.
- kb.karel.in/obsidian/ answers 502: `kb-web` was suspended 2026-09-21 and nothing serves 127.0.0.1:8086 on trix.
