<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/data.py 893e585cce65326aefbc3cb9283f44347bdd134d -->
# gppu.data

`gppu.data` gives programs database access, a key/value cache with a time to live, and a way to save and reload `_DC` objects in a database or file. Each part can be used on its own.

## Database access

`_PGBase` runs raw SQL on PostgreSQL through psycopg2. Its `connection` opens on first use, and its `cursor()` context manager commits when the block ends and rolls back on an error. `_SQABase` gives SQLModel ORM access through SQLAlchemy's async engine on psycopg 3, built by `async_engine()`. Its `session()` is one session that commits on exit and rolls back on an error. Its `scoped_session` gives each asyncio task its own session. Both classes inherit from `_PersistentBase`, which reads the connection string from the `db` key, found through `Env.glob('db')` or `self.my('db')`, and raises `ValueError` when none is set. `_SQABase` needs the `ld` extra.

## Caching

`Cache` is a standalone key/value cache. It does not need `Env` or configuration. It takes one of five backends: json, pickle, sqlite, diskcache, or db, which takes any SQLAlchemy URL. The default time to live is 86400 seconds. An unknown backend name raises `ValueError`; no other backend is substituted. Setting the environment variable named by `skip_env`, which defaults to `SKIP_CACHE`, to `true`, `1`, or `yes` turns the cache off. Then `get` returns the default, `set` does nothing, and the decorator returns the function unchanged. Used as a decorator, `Cache` memoizes a function's results. Its `get`, `set`, and `delete` catch exceptions, so cache errors do not reach the caller.

## Persistence

`_PersistentDC` is a `_DC` whose `data` is saved through a backend bound once per process with `bind_db`. Saved rows are namespaced by the class name and by the value of `data` under `_persist_key`, which defaults to `'gppu'`. `persist()` saves the object, `load(key)` returns the saved dict or `None`, and `iter_all()` yields every saved row for the class. Without a bound backend, these calls do nothing or return `None`. A subclass that needs other storage overrides `_do_persist()`.

`Persistence` is the standard factory for these backends. Its backends are json, pickle, sqlite, and postgres, where the target is a connection string.

## Usage

```python
from gppu.data import Persistence, _PersistentDC

_PersistentDC.bind_db(Persistence('/var/lib/y2.db', backend='sqlite'))
```
