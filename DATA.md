# gppu.data - Database & Caching

`gppu.data` provides database access classes built on top of `_Base` (from `gppu.ad`), combining logging, config management, and connection lifecycle. It also includes `Cache`, a standalone multi-backend key/value cache.

```python
from gppu.data import _PGBase, _SQABase, Cache
```

## Inheritance Chain

```
mixin_Logger + mixin_Config
        ↓
      _Base          (logger + config, from gppu.ad)
        ↓
  _PersistentBase    (connection string resolution, context manager)
      ↓       ↓
  _PGBase    _SQABase
```

## _PersistentBase

Abstract base for all database-backed components. Resolves the connection string from `Env.glob('db')` first, then `self.my('db')` (from config_key). Raises `ValueError` if neither is found.

Supports context manager protocol (`with` statement) for automatic cleanup.

## _PGBase - PostgreSQL (psycopg2)

Direct SQL execution with lazy connection and dict cursors.

```python
from gppu.data import _PGBase

class MyDB(_PGBase):
    pass

# Context manager closes connection on exit
with MyDB(config_key='postgres') as db:

    # cursor() returns a context manager with auto-commit/rollback
    with db.cursor() as cur:
        cur.execute('SELECT * FROM users WHERE active = %s', (True,))
        rows = cur.fetchall()  # list of RealDictRow (dict-like)

    # Use dict_cursor=False for tuple cursors
    with db.cursor(dict_cursor=False) as cur:
        cur.execute('SELECT count(*) FROM users')
        count = cur.fetchone()[0]

    # Direct connection access (lazy - connects on first use)
    db.connection  # psycopg2 connection object
```

Config example:
```yaml
# In your app config YAML
postgres:
  db: "postgresql://user:pass@localhost:5432/mydb"
```

Requires `psycopg2-binary`: `pip install "gppu[pg] @ git+ssh://git@github.com/akarelin/gppu.git@gppu/latest"`

## _SQABase - SQLAlchemy ORM

ORM session management with lazy engine creation.

```python
from gppu.data import _SQABase

class MyORM(_SQABase):
    pass

with MyORM(config_key='database') as db:

    # session() returns a context manager with auto-commit/rollback
    with db.session() as sess:
        users = sess.query(User).all()
        sess.add(User(name='new'))

    # Direct engine access (lazy - creates on first use)
    db.engine  # SQLAlchemy engine object

# Or without context manager (call .close() manually)
db = MyORM(config_key='database')
with db.session() as sess:
    ...
db.close()  # disposes engine connection pool
```

Requires `sqlalchemy`: `pip install "gppu[sql] @ git+ssh://git@github.com/akarelin/gppu.git@gppu/latest"`

## Connection String Resolution

Both classes resolve `db_connection_string` in this order:

1. `Env.glob('db')` - top-level `db` key in global config
2. `self.my('db')` - `db` key within the config_key subsection

This means you can have a global default or per-component overrides:

```yaml
# Global default
db: "postgresql://user:pass@localhost/default_db"

# Per-component override
postgres:
  db: "postgresql://user:pass@localhost/specific_db"
  base_dir: "/data/postgres"
```

## Cache - Multi-Backend Key/Value Cache

Standalone cache with TTL support, multiple backends, and environment variable bypass. Does **not** require `Env` or config initialization.

```python
from gppu.data import Cache

# SQLite backend (default, no extra deps)
cache = Cache('/tmp/my_cache', ttl=3600, backend='sqlite')
cache.set('key', {'data': [1, 2, 3]})
result = cache.get('key')          # {'data': [1, 2, 3]}
cache.get('missing')               # None
cache.get('missing', default=42)   # 42
cache.delete('key')

# Per-key TTL override
cache.set('short_lived', 'val', ttl=10)   # expires in 10s
cache.set('long_lived', 'val', ttl=3600)  # expires in 1h
cache.set('permanent', 'val', ttl=0)      # no expiration

# Use as decorator for automatic memoization
cache = Cache('/tmp/fn_cache', ttl=300)

@cache
def expensive_computation(x):
    return x * 2

expensive_computation(5)  # computed
expensive_computation(5)  # served from cache
```

### Constructor

```python
Cache(directory, ttl=86400, *, backend='sqlite', skip_env='SKIP_CACHE')
```

| Parameter   | Default        | Description |
|-------------|----------------|-------------|
| `directory` | *(required)*   | Cache path (file/dir) or DB URL for `db` backend |
| `ttl`       | `86400` (24h)  | Default TTL in seconds |
| `backend`   | `'sqlite'`     | Storage backend (see below) |
| `skip_env`  | `'SKIP_CACHE'` | Env var name that bypasses caching when set to `true`/`1`/`yes`. Empty string disables this check |

### Backends

| Backend     | Path type     | Dependencies |
|-------------|---------------|--------------|
| `json`      | File path     | None (stdlib) |
| `pickle`    | File path     | None (stdlib) |
| `sqlite`    | File/dir path | None (stdlib) |
| `diskcache` | Directory     | `pip install gppu[cache]` |
| `db`        | SQLAlchemy URL | `pip install gppu[sql]` |

### Methods

| Method | Description |
|--------|-------------|
| `get(key, default=None)` | Retrieve cached value, or `default` if missing/expired |
| `set(key, value, ttl=None)` | Store value. Uses instance TTL if `ttl` is `None`; `ttl=0` means no expiration |
| `delete(key)` | Remove a key |
| `close()` | Close the cache |
| `skip` (property) | `True` if caching is bypassed via env var |

Supports context manager protocol and `@cache` decorator for function memoization.

### Env-Var Bypass

Set the environment variable named in `skip_env` to `true`, `1`, or `yes` to disable all caching (reads return `default`, writes are no-ops, decorator passes through). Useful for testing or debugging.

```bash
SKIP_CACHE=true python my_script.py  # all cache reads return default
```
