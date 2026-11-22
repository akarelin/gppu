from __future__ import annotations

import asyncio, functools, hashlib, json, pickle, sqlite3, threading, time

from typing import Any, ClassVar, Optional
from contextlib import asynccontextmanager, contextmanager

from .gppu import Path, _Base
from .gppu import glob
from .gppu import _DC


class _PersistentBase(_Base):
  """Base class for database-backed components.

  Handles common DB connection string resolution from config.
  Subclasses: _PGBase (psycopg2), _SQABase (SQLAlchemy)
  """
  db_connection_string: str

  def __init__(self, **kw):
    super().__init__(**kw)
    self.db_connection_string = glob('db') or (self.my('db') if isinstance(self, _DC) else '')   # .. the environment's db, else the own configuration's of an app built on this
    if not self.db_connection_string:
      raise ValueError("Database connection string 'db' not found in config")

  def close(self):
    """Close database connection. Override in subclasses."""
    pass

  def __enter__(self):
    return self

  def __exit__(self, *_):
    self.close()


class _PGBase(_PersistentBase):
  """PostgreSQL database access using psycopg2.

  Provides direct SQL execution with connection pooling.
  Use for raw SQL queries and performance-critical operations.
  """
  _connection: Any

  def __init__(self, **kw):
    super().__init__(**kw)
    self._connection = None

  @property
  def connection(self):
    """Lazy connection - connects on first use."""
    if self._connection is None:
      import psycopg2
      self._connection = psycopg2.connect(self.db_connection_string)
    return self._connection

  @contextmanager
  def cursor(self, dict_cursor: bool = True):
    """Context manager for database cursor with auto-commit/rollback."""
    from psycopg2.extras import RealDictCursor
    cursor_factory = RealDictCursor if dict_cursor else None
    cur = self.connection.cursor(cursor_factory=cursor_factory)
    try:
      yield cur
      self.connection.commit()
    except Exception:
      self.connection.rollback()
      raise
    finally:
      cur.close()

  def close(self):
    """Close the database connection."""
    if self._connection:
      self._connection.close()
      self._connection = None


def async_engine(dsn: str):
  """SQLAlchemy's async engine on psycopg 3 for the Postgres at `dsn`, its session's zone UTC, so a time without a zone is
  compared as UTC. A `postgresql://` dsn is taken as psycopg 3's. Needs the `ld` extra."""
  from sqlalchemy.ext.asyncio import create_async_engine
  if dsn.startswith('postgresql://'): dsn = 'postgresql+psycopg://' + dsn.removeprefix('postgresql://')
  return create_async_engine(dsn, connect_args={'options': '-c timezone=UTC'})


class _SQABase(_PersistentBase):
  """SQLModel ORM database access: SQLAlchemy's async engine on psycopg 3 (`async_engine`), as gppu.ld uses it.

  `session()` is one database session, committed when it closes and rolled back on an error. `scoped_session` is
  SQLAlchemy's `async_scoped_session` on the engine: called, it gives the session of the asyncio task calling, so each
  request served has its own without passing it along; `remove()` closes it.
  Needs the `ld` extra.
  """
  _engine: Any
  _scoped: Any

  def __init__(self, **kw):
    super().__init__(**kw)
    self._engine = None
    self._scoped = None

  @property
  def engine(self):
    """Lazy engine - creates on first use."""
    if self._engine is None: self._engine = async_engine(self.db_connection_string)
    return self._engine

  @property
  def scoped_session(self):
    """The session of the asyncio task calling, one per task (SQLAlchemy's async_scoped_session); made on first use."""
    if self._scoped is None:
      from sqlalchemy.ext.asyncio import async_scoped_session, async_sessionmaker
      from sqlmodel.ext.asyncio.session import AsyncSession
      self._scoped = async_scoped_session(async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False), scopefunc=asyncio.current_task)
    return self._scoped

  @asynccontextmanager
  async def session(self):
    """Async context manager for an ORM session with auto-commit/rollback."""
    from sqlmodel.ext.asyncio.session import AsyncSession
    async with AsyncSession(self.engine, expire_on_commit=False) as sess:
      try:
        yield sess
        await sess.commit()
      except Exception:
        await sess.rollback()
        raise

  async def close(self):
    """Dispose the engine connection pool."""
    if self._engine:
      await self._engine.dispose()
      self._engine = None

  async def __aenter__(self):
    return self

  async def __aexit__(self, *_):
    await self.close()


class _PersistentDC(_DC):
  """_DC subclass that persists self.data through a pluggable backend.

  Storage is namespaced by (type(self).__name__, self.data[_persist_key]).
  Subclasses wanting custom storage override _do_persist() / load().

  Backend protocol (duck-typed; see `gppu.data.Persistence` for the standard
  factory and built-in backends: json, pickle, sqlite):
    upsert(cls: str, key: str, data: dict) -> None
    load(cls: str, key: str)   -> dict | None
    delete(cls: str, key: str) -> None
    close()                    -> None

  Bind once per process:
    from gppu.data import Persistence
    _PersistentDC.bind_db(Persistence('/var/lib/y2.db', backend='sqlite'))
  """

  _persist_key: ClassVar[str] = 'gppu'
  _persist_db:  ClassVar[Any] = None

  @classmethod
  def bind_db(cls, db: Any) -> None: cls._persist_db = db

  def persist(self) -> None:
    db = type(self)._persist_db
    if db is None: return
    pk = self.data.get(self._persist_key)
    if not pk: return
    self._do_persist(db, str(pk))

  def _do_persist(self, db: Any, pk: str) -> None:
    db.upsert(type(self).__name__, pk, dict(self.data))

  @classmethod
  def load(cls, key: str) -> Optional[dict]:
    db = cls._persist_db
    if db is None: return None
    return db.load(cls.__name__, str(key))

  @classmethod
  def iter_all(cls):
    """Yield (key, data) for every persisted row of this class. Empty if unbound."""
    db = cls._persist_db
    if db is None: return
    yield from db.iter(cls.__name__)
# endregion


class _FileBackend:
  """File cache backend: one file, json or pickle as its serializer. No dependencies."""

  def __init__(self, path: str, serializer, name: str):
    self._serializer, self._binary = serializer, serializer is pickle
    self._path = Path(path) / name if Path(path).is_dir() else Path(path)
    self._path.parent.mkdir(parents=True, exist_ok=True)
    self._data: dict = {}
    if self._path.exists():
      with self._path.open('rb' if self._binary else 'r') as f: self._data = self._serializer.load(f)

  def _flush(self):
    with self._path.open('wb' if self._binary else 'w') as f: self._serializer.dump(self._data, f)

  def _alive(self, entry: dict) -> bool:
    exp = entry.get('_exp')
    return exp is None or time.time() < exp

  def get(self, key: str, default=None):
    entry = self._data.get(key)
    if entry is None or not self._alive(entry): return default
    return entry.get('v', default)

  def set(self, key: str, value, expire=None):
    entry: dict = {'v': value}
    if expire is not None: entry['_exp'] = time.time() + expire
    self._data[key] = entry
    self._flush()

  def delete(self, key: str):
    self._data.pop(key, None)
    self._flush()

  def close(self): self._flush()


class _SqliteBackend:
  """SQLite cache backend. No external dependencies (stdlib sqlite3)."""

  def __init__(self, path: str):
    path = Path(path) / '_cache.db' if Path(path).is_dir() else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    self._conn = sqlite3.connect(path)
    self._conn.execute(
      'CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB, expire REAL)')

  def get(self, key: str, default=None):
    row = self._conn.execute('SELECT value, expire FROM cache WHERE key=?', (key,)).fetchone()
    if row is None: return default
    if row[1] is not None and time.time() >= row[1]:
      self._conn.execute('DELETE FROM cache WHERE key=?', (key,))
      self._conn.commit()
      return default
    return pickle.loads(row[0])

  def set(self, key: str, value, expire=None):
    exp = (time.time() + expire) if expire else None
    self._conn.execute('INSERT OR REPLACE INTO cache (key, value, expire) VALUES (?, ?, ?)',
                       (key, pickle.dumps(value), exp))
    self._conn.commit()

  def delete(self, key: str):
    self._conn.execute('DELETE FROM cache WHERE key=?', (key,))
    self._conn.commit()

  def close(self):
    if self._conn: self._conn.close(); self._conn = None


_BACKENDS = {
  'json': lambda path: _FileBackend(path, json, '_cache.json'),
  'pickle': lambda path: _FileBackend(path, pickle, '_cache.pkl'),
  'sqlite': _SqliteBackend,
}


class Cache:
  """Key/value cache with TTL.

  Standalone utility -- does not require Env or config initialization.

  Backends (explicit, no fallback):
    json      — JSON file, no deps
    pickle    — pickle file, no deps
    sqlite    — stdlib sqlite3
  """
  _cache: Any
  _ttl: int

  def __init__(self, directory: str, ttl: int = 86400, *, backend: str = 'sqlite'):
    """
    Args:
      directory:  Cache path (file/dir).
      ttl:        Default TTL in seconds (default: 86400 = 24h).
      backend:    'json', 'pickle' or 'sqlite'.
    """
    self._ttl = ttl
    if backend not in _BACKENDS:
      raise ValueError(f"Unknown backend {backend!r}, expected one of: {', '.join(_BACKENDS)}")
    self._cache = _BACKENDS[backend](directory)

  def get(self, key: str, default: Any = None) -> Any:
    return self._cache.get(key, default)

  def set(self, key: str, value: Any, ttl: int | None = None) -> None:
    self._cache.set(key, value, expire=self._ttl if ttl is None else (ttl or None))

  def delete(self, key: str) -> None: self._cache.delete(key)

  def __call__(self, fn):
    """Use as @cache decorator for automatic memoization."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
      k = f'memo:{fn.__module__}.{fn.__qualname__}:{hashlib.md5(repr((args, kwargs)).encode()).hexdigest()}'
      cached = self.get(k)
      if cached is not None: return cached
      result = fn(*args, **kwargs)
      self.set(k, result)
      return result
    return wrapper

  def close(self):
    if self._cache: self._cache.close(); self._cache = None

  def __enter__(self): return self
  def __exit__(self, *_): self.close()


# region - Persistence backends for _PersistentDC
#
# region - backend interface
# .. Backend interface (duck-typed):
# ..   upsert(cls: str, key: str, data: dict) -> None
# ..   load(cls: str, key: str) -> dict | None
# ..   delete(cls: str, key: str) -> None
# ..   close() -> None
# ..
# .. All backends namespace storage by (cls, key) pair.
# endregion

class _FilePersistBackend:
  """File backend: one file, nested dict {cls: {key: data}}, json or pickle as its serializer. No deps."""

  def __init__(self, path: str, serializer, name: str):
    self._serializer, self._binary = serializer, serializer is pickle
    self._path = Path(path) / name if Path(path).is_dir() else Path(path)
    self._path.parent.mkdir(parents=True, exist_ok=True)
    self._data: dict[str, dict[str, dict]] = {}
    if self._path.exists():
      with self._path.open('rb' if self._binary else 'r') as f: self._data = self._serializer.load(f)

  def _flush(self):
    with self._path.open('wb' if self._binary else 'w') as f: self._serializer.dump(self._data, f)

  def upsert(self, cls: str, key: str, data: dict) -> None:
    self._data.setdefault(cls, {})[key] = data
    self._flush()

  def load(self, cls: str, key: str) -> Optional[dict]:
    return self._data.get(cls, {}).get(key)

  def iter(self, cls: str):
    for k, v in self._data.get(cls, {}).items(): yield k, dict(v)

  def delete(self, cls: str, key: str) -> None:
    if self._data.get(cls, {}).pop(key, None) is not None: self._flush()

  def close(self): self._flush()


class _SqlitePersistBackend:
  """SQLite backend. One file, one table `persistent_dc(cls, key, data)`. Stdlib only."""

  def __init__(self, path: str):
    path = Path(path) / '_persist.db' if Path(path).is_dir() else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    self._conn = sqlite3.connect(path, check_same_thread=False)
    self._lock = threading.Lock()
    self._conn.execute(
      'CREATE TABLE IF NOT EXISTS persistent_dc '
      '(cls TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, '
      ' updated_at REAL NOT NULL, PRIMARY KEY (cls, key))')
    self._conn.commit()

  def upsert(self, cls: str, key: str, data: dict) -> None:
    with self._lock:
      self._conn.execute(
        'INSERT OR REPLACE INTO persistent_dc (cls, key, data, updated_at) VALUES (?, ?, ?, ?)',
        (cls, key, json.dumps(data), time.time()))
      self._conn.commit()

  def load(self, cls: str, key: str) -> Optional[dict]:
    with self._lock:
      row = self._conn.execute(
        'SELECT data FROM persistent_dc WHERE cls=? AND key=?', (cls, key)).fetchone()
    return json.loads(row[0]) if row else None

  def iter(self, cls: str):
    with self._lock:
      rows = self._conn.execute(
        'SELECT key, data FROM persistent_dc WHERE cls=? ORDER BY key', (cls,)).fetchall()
    for k, d in rows: yield k, json.loads(d)

  def delete(self, cls: str, key: str) -> None:
    with self._lock:
      self._conn.execute('DELETE FROM persistent_dc WHERE cls=? AND key=?', (cls, key))
      self._conn.commit()

  def close(self):
    if self._conn: self._conn.close(); self._conn = None  # type: ignore[assignment]


_PERSIST_BACKENDS = {
  'json':     lambda path: _FilePersistBackend(path, json, '_persist.json'),
  'pickle':   lambda path: _FilePersistBackend(path, pickle, '_persist.pkl'),
  'sqlite':   _SqlitePersistBackend,
}


class Persistence:
  """Storage for `_PersistentDC` instances, multi-backend.

  Mirrors the `Cache` class shape.

  Backends (explicit, no fallback):
    json      — JSON file, no deps
    pickle    — pickle file, no deps
    sqlite    — stdlib sqlite3

  Usage:
    p = Persistence('/var/lib/y2/persist.db', backend='sqlite')

    _PersistentDC.bind_db(p)
  """

  def __init__(self, target: str, *, backend: str = 'sqlite'):
    if backend not in _PERSIST_BACKENDS:
      raise ValueError(f"Unknown backend {backend!r}, expected one of: {', '.join(_PERSIST_BACKENDS)}")
    self._b = _PERSIST_BACKENDS[backend](target)

  def upsert(self, cls: str, key: str, data: dict) -> None: self._b.upsert(cls, key, data)
  def load(self, cls: str, key: str) -> Optional[dict]: return self._b.load(cls, key)
  def iter(self, cls: str): yield from self._b.iter(cls)
  def delete(self, cls: str, key: str) -> None: self._b.delete(cls, key)
  def close(self):
    if self._b: self._b.close(); self._b = None  # type: ignore[assignment]

  def __enter__(self): return self
  def __exit__(self, *_): self.close()
# endregion


