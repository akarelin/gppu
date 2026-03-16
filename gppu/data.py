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


class DiskCache:
  """Disk-backed key/value cache with TTL and env-var bypass.

  Standalone utility -- does not require Env or config initialization.
  Requires: pip install "gppu[cache]"
  """
  _cache: Any
  _ttl: int
  _skip: bool

  def __init__(self, directory: str, ttl: int = 86400, *, skip_env: str = 'SKIP_CACHE'):
    """
    Args:
      directory:  Cache directory path (supports ~ expansion).
      ttl:        Default TTL in seconds (default: 86400 = 24h).
      skip_env:   Env var name to check for bypass (empty string disables).
    """
    import os
    from diskcache import Cache
    self._ttl = ttl
    self._skip = bool(skip_env and os.getenv(skip_env, '').lower() in ('true', '1', 'yes'))
    self._cache = Cache(os.path.expanduser(directory))

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
    try: return self._cache.memoize(expire=self._ttl)(fn)
    except Exception: return fn

  def close(self):
    if self._cache: self._cache.close(); self._cache = None

  def __enter__(self): return self
  def __exit__(self, *_): self.close()
