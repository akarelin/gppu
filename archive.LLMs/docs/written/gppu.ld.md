<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/ld/__init__.py 9bbd32811362137f943b229dc525e45c3b79cd50 -->
Linked Data (`gppu.ld`) stores records and the links between them on Postgres, and builds the API of each type from the same operations. Every record, whatever its type, is created, read, updated, deleted, listed and searched by one set of rules.

The module needs the `ld` extra. Install fastapi-querybuilder with `--no-deps`, because its metadata lists poetry, uvicorn and aiosqlite as runtime dependencies.

## How the classes work together

`_Record` holds the columns every record has and the operations on them. It has no table of its own. A caller sends a record without the columns Postgres fills, and a field the type does not have is refused.

The data models add columns to a record without a table. `_Event` adds `ts`, `_Activity` adds `span`, `_View` adds `query` and `last_refreshed`, and `_Link` adds `from_id` and `to_id`. A type's class takes the data model it needs and sets `table=True` to define its table. The core types are `Record`, `Node`, `Collection`, `View`, `Event`, `Message`, `Activity` and `Link`. A domain defines its own types the same way, in its own module. The store's `schema.sql` makes the tables, and Postgres' inheritance links them.

`operations()` builds five routes for a path: create, read, update, delete and search. Each route works on the table of the record's type. `app` is the core API, with `/records` and `/links`, `/types`, and the lists of a record's children and links. `api_at()` builds a domain's API at its own path with its own documentation. `serve()` puts the core and those APIs in one application on one store, and makes each request one transaction. The store is a `gppu.data._SQABase`. `types_agree()` checks that the store's `record_types` match the `Type` codes, and raises if they differ.

## Use

Pass the types a domain uses to `operations()`, with the body a caller sends and a name for the documentation. Give the result a path with `api_at()`, then mount the APIs on the app's store with `serve()`.

```python
from gppu.data import _SQABase
from gppu.ld import Fields, Node, api_at, operations, serve

store = ...   # the app's _SQABase
nodes = api_at('/nodes', 'nodes', 'Nodes', operations('/nodes', Fields, 'node', Node))
api = serve({'/nodes': nodes}, store)
```
