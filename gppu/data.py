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
