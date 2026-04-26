from __future__ import annotations

from typing import Any
from contextlib import contextmanager

from .gppu import Env
from .ad import _Base


class _PersistentBase(_Base):
  """Base class for database-backed components.

  Handles common DB connection string resolution from config.
  Subclasses: _PGBase (psycopg2), _SQABase (SQLAlchemy)
  """
  db_connection_string: str

  def __init__(self, **kw):
    super().__init__(**kw)
    self.db_connection_string = Env.glob('db') or self.my('db') or ''
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


class _SQABase(_PersistentBase):
  """SQLAlchemy ORM database access.

  Provides ORM session management with declarative models.
  Use with _DM base class for model definitions.
  """
  _engine: Any
  _Session: Any

  def __init__(self, **kw):
    super().__init__(**kw)
    self._engine = None
    self._Session = None

  @property
  def engine(self):
    """Lazy engine - creates on first use."""
    if self._engine is None:
      from sqlalchemy import create_engine
      from sqlalchemy.orm import sessionmaker
      self._engine = create_engine(self.db_connection_string, echo=False)
      self._Session = sessionmaker(bind=self._engine)
    return self._engine

  @contextmanager
  def session(self):
    """Context manager for database session with auto-commit/rollback."""
    _ = self.engine  # ensure engine is created
    sess = self._Session()
    try:
      yield sess
      sess.commit()
    except Exception:
      sess.rollback()
      raise
    finally:
      sess.close()

  def close(self):
    """Dispose the engine connection pool."""
    if self._engine:
      self._engine.dispose()
      self._engine = None
      self._Session = None


class _JsonBackend:
  """JSON-file cache backend. No dependencies."""

  def __init__(self, path: str):
    import os, json
    self._path = path
    self._data: dict = {}
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path):
      self._path = os.path.join(path, '_cache.json')
    try:
      with open(self._path) as f: self._data = json.load(f)
    except Exception: pass

  def _flush(self):
    import json
    try:
      with open(self._path, 'w') as f: json.dump(self._data, f)
    except Exception: pass

  def _alive(self, entry: dict) -> bool:
    import time
    exp = entry.get('_exp')
    return exp is None or time.time() < exp

  def get(self, key: str, default=None):
    entry = self._data.get(key)
    if entry is None or not self._alive(entry): return default
    return entry.get('v', default)

  def set(self, key: str, value, expire=None):
    import time
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
    import os, sqlite3
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path):
      path = os.path.join(path, '_cache.db')
    self._conn = sqlite3.connect(path)
    self._conn.execute(
      'CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB, expire REAL)')

  def get(self, key: str, default=None):
    import pickle, time
    row = self._conn.execute('SELECT value, expire FROM cache WHERE key=?', (key,)).fetchone()
    if row is None: return default
    if row[1] is not None and time.time() >= row[1]:
      self._conn.execute('DELETE FROM cache WHERE key=?', (key,))
      self._conn.commit()
      return default
    return pickle.loads(row[0])

  def set(self, key: str, value, expire=None):
    import pickle, time
    exp = (time.time() + expire) if expire else None
    self._conn.execute('INSERT OR REPLACE INTO cache (key, value, expire) VALUES (?, ?, ?)',
                       (key, pickle.dumps(value), exp))
    self._conn.commit()

  def delete(self, key: str):
    self._conn.execute('DELETE FROM cache WHERE key=?', (key,))
    self._conn.commit()

  def close(self):
    if self._conn: self._conn.close(); self._conn = None


class _PickleBackend:
  """Pickle-file cache backend. No external dependencies."""

  def __init__(self, path: str):
    import os, pickle
    self._path = path
    self._data: dict = {}
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path):
      self._path = os.path.join(path, '_cache.pkl')
    try:
      with open(self._path, 'rb') as f: self._data = pickle.load(f)
    except Exception: pass

  def _flush(self):
    import pickle
    try:
      with open(self._path, 'wb') as f: pickle.dump(self._data, f)
    except Exception: pass

  def _alive(self, entry: dict) -> bool:
    import time
    exp = entry.get('_exp')
    return exp is None or time.time() < exp

  def get(self, key: str, default=None):
    entry = self._data.get(key)
    if entry is None or not self._alive(entry): return default
    return entry.get('v', default)

  def set(self, key: str, value, expire=None):
    import time
    entry: dict = {'v': value}
    if expire is not None: entry['_exp'] = time.time() + expire
    self._data[key] = entry
    self._flush()

  def delete(self, key: str):
    self._data.pop(key, None)
    self._flush()

  def close(self): self._flush()


class _DiskcacheBackend:
  """diskcache backend. Requires: pip install diskcache"""

  def __init__(self, path: str):
    from diskcache import Cache
    self._cache = Cache(path)

  def get(self, key: str, default=None): return self._cache.get(key, default)
  def set(self, key: str, value, expire=None): self._cache.set(key, value, expire=expire)
  def delete(self, key: str): self._cache.delete(key)
  def close(self): self._cache.close(); self._cache = None


class _DbBackend:
  """SQLAlchemy-based cache backend for any remote database."""

  def __init__(self, url: str):
    from sqlalchemy import create_engine, text
    self._engine = create_engine(url)
    with self._engine.connect() as conn:
      conn.execute(text(
        'CREATE TABLE IF NOT EXISTS cache (key VARCHAR(512) PRIMARY KEY, value BYTEA, expire FLOAT)'))
      conn.commit()

  def get(self, key: str, default=None):
    import pickle, time
    from sqlalchemy import text
    with self._engine.connect() as conn:
      row = conn.execute(text('SELECT value, expire FROM cache WHERE key=:k'), {'k': key}).fetchone()
    if row is None: return default
    if row[1] is not None and time.time() >= row[1]:
      self.delete(key)
      return default
    return pickle.loads(row[0])

  def set(self, key: str, value, expire=None):
    import pickle, time
    from sqlalchemy import text
    exp = (time.time() + expire) if expire else None
    blob = pickle.dumps(value)
    with self._engine.connect() as conn:
      conn.execute(text(
        'INSERT INTO cache (key, value, expire) VALUES (:k, :v, :e) '
        'ON CONFLICT (key) DO UPDATE SET value=:v, expire=:e'),
        {'k': key, 'v': blob, 'e': exp})
      conn.commit()

  def delete(self, key: str):
    from sqlalchemy import text
    with self._engine.connect() as conn:
      conn.execute(text('DELETE FROM cache WHERE key=:k'), {'k': key})
      conn.commit()

  def close(self):
    if self._engine: self._engine.dispose(); self._engine = None


_BACKENDS = {
  'json': _JsonBackend,
  'pickle': _PickleBackend,
  'sqlite': _SqliteBackend,
  'diskcache': _DiskcacheBackend,
  'db': _DbBackend,
}


DiskCache = None  # removed, use Cache


class Cache:
  """Key/value cache with TTL and env-var bypass.

  Standalone utility -- does not require Env or config initialization.

  Backends (explicit, no fallback):
    json      — JSON file, no deps
    pickle    — pickle file, no deps
    sqlite    — stdlib sqlite3
    diskcache — pip install diskcache
    db        — any SQLAlchemy URL (postgres, mysql, etc.)
  """
  _cache: Any
  _ttl: int
  _skip: bool

  def __init__(self, directory: str, ttl: int = 86400, *,
               backend: str = 'sqlite', skip_env: str = 'SKIP_CACHE'):
    """
    Args:
      directory:  Cache path (file/dir) or DB URL for 'db' backend.
      ttl:        Default TTL in seconds (default: 86400 = 24h).
      backend:    'json', 'pickle', 'sqlite', 'diskcache', or 'db'.
      skip_env:   Env var name to check for bypass (empty string disables).
    """
    import os
    self._ttl = ttl
    self._skip = bool(skip_env and os.getenv(skip_env, '').lower() in ('true', '1', 'yes'))
    if backend not in _BACKENDS:
      raise ValueError(f"Unknown backend {backend!r}, expected one of: {', '.join(_BACKENDS)}")
    path = directory if backend == 'db' else os.path.expanduser(directory)
    self._cache = _BACKENDS[backend](path)

  @property
  def skip(self) -> bool: return self._skip

  def get(self, key: str, default: Any = None) -> Any:
    if self._skip: return default
    try: return self._cache.get(key, default)
    except Exception: return default

  def set(self, key: str, value: Any, ttl: int | None = None) -> None:
    if self._skip: return
    try: self._cache.set(key, value, expire=self._ttl if ttl is None else (ttl or None))
    except Exception: pass

  def delete(self, key: str) -> None:
    try: self._cache.delete(key)
    except Exception: pass

  def __call__(self, fn):
    """Use as @cache decorator for automatic memoization."""
    if self._skip: return fn
    import functools, hashlib
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


# region Human-readable formatters

def format_size(size: int | float) -> str:
  """Format byte count as '0 B', '1.5 KB', '2.3 MB', '4.5 GB', '7.8 TB'.

  Powers-of-1024 (binary). One decimal for KB+, two for TB.
  """
  size = float(size)
  if size < 1024:                  return f"{int(size)} B"
  if size < 1024 ** 2:             return f"{size / 1024:.1f} KB"
  if size < 1024 ** 3:             return f"{size / 1024 ** 2:.1f} MB"
  if size < 1024 ** 4:             return f"{size / 1024 ** 3:.1f} GB"
  return f"{size / 1024 ** 4:.2f} TB"


def format_duration(seconds: int | float) -> str:
  """Format a duration as '0s' / '5s' / '12m 30s' / '2h 5m'.

  Input is seconds (use ``ms / 1000`` for millisecond inputs).  Returns
  ``'-'`` for negative values; ``0`` formats as ``'0s'`` so callers using
  this for uptime get a legitimate zero rather than a placeholder.
  """
  seconds = float(seconds)
  if seconds < 0: return "-"
  if seconds < 60: return f"{seconds:.0f}s"
  if seconds < 3600:
    m, s = divmod(seconds, 60)
    return f"{int(m)}m {int(s)}s"
  h, rem = divmod(seconds, 3600)
  m, _ = divmod(rem, 60)
  return f"{int(h)}h {int(m)}m"


def format_since(when) -> str:
  """Compact "time since" — '5s', '5m', '2h', '3d', '4w', '6mo', '2y'.

  Accepts ISO-8601 string, ``datetime``, or epoch seconds (int/float).
  Returns empty string on parse failure.  Negative deltas (future timestamps)
  return ``'0s'``.
  """
  from datetime import datetime, timezone

  dt = None
  if isinstance(when, datetime):
    dt = when
  elif isinstance(when, (int, float)):
    dt = datetime.fromtimestamp(float(when), tz=timezone.utc)
  elif isinstance(when, str):
    s = when.strip()
    if not s: return ""
    if s.endswith('Z'): s = s[:-1] + '+00:00'
    try: dt = datetime.fromisoformat(s)
    except ValueError: return ""
  else:
    return ""

  if dt.tzinfo is None:
    dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)

  secs = int((datetime.now(timezone.utc) - dt).total_seconds())
  if secs < 0:    return "0s"
  if secs < 60:   return f"{secs}s"
  mins = secs // 60
  if mins < 60:   return f"{mins}m"
  hrs = mins // 60
  if hrs < 24:    return f"{hrs}h"
  days = hrs // 24
  if days < 7:    return f"{days}d"
  if days < 30:   return f"{days // 7}w"
  if days < 365:  return f"{days // 30}mo"
  return f"{days // 365}y"

# endregion
