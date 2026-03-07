from __future__ import annotations

import sys

from pathlib import Path
from collections import UserDict
from typing import Any, Callable
from contextlib import contextmanager

from .gppu import mixin_Logger, mixin_Config, Env


# region DC - pseudo DataClass
_DC_BASE_TYPE_MAP = {'str': str, 'list': list, 'dict': dict, 'set': set, 'int': int, 'float': float, 'bool': bool, 'None': type(None)}


class DC(UserDict):
  _DC_TYPE_MAP: dict[str, type] = _DC_BASE_TYPE_MAP.copy()
  _DC_EXCLUDE_NAMES: list[str] = []


  def _init_from_kw(self, **kw) -> None:
    data = kw.pop('data', {})
    if isinstance(data, str): data = {'data': data}
    self.data = kw | data


  _INIT_STEPS: list[Callable] = [_init_from_kw]


  def __init_subclass__(cls, **kw) -> None:
    def _simple_type(typ: type | str) -> str:
      typ = str(typ)
      if typ.startswith('list['): return 'list'
      return typ

    super().__init_subclass__(**kw)

    annotations_raw = [(n, t if type(t) == str else str(t.__name__)) for c in cls.mro() if hasattr(c, '__annotations__') for n, t in c.__annotations__.items() if n[0] != '_' and n not in cls._DC_EXCLUDE_NAMES]
    annotations = {n: _simple_type(t) for n, t in annotations_raw}

    mro = [(n, t) for n, t in annotations.items() if n[0] != '_' and t in cls._DC_TYPE_MAP]
    for aname, atype in mro:
      def getter(self, name=aname, atype=atype):
        result = self.data.get(name)
        if result is not None and isinstance(result, cls._DC_TYPE_MAP[atype]): return result
        if not result:
          if atype == 'str': result = ''
          elif atype == 'list': result = []
          elif atype == 'dict': result = {}
          elif atype == 'set': result = set()
        return result
      def setter(self, value, name=aname, type_hint=atype, _owner_mod=sys.modules[cls.__module__]):
        if not hasattr(self, 'data'): self.data = {}
        self.data[name] = value
      setattr(cls, aname, property(getter, setter))


  def __init__(self, **kw):
    self.data = {}
    for step in self._INIT_STEPS: step(self, **kw)
# endregion


# region Foundation
class _Logger(mixin_Logger): pass


class _Config(mixin_Config):
  _base_path: Path

  def __init__(self, **kw) -> None:
    super().__init__()
    assert Env.initialized, "Env must be initialized"
    key = kw.get('config_key', None)

    if key:
      self._config_from_key(key)
      self._base_path = Path(self.my('base_dir'))
    else:
      self._config_from_env()
      self._base_path = Path('.')

  def my_path(self, path) -> Path: return self._base_path / self.my(path)


class _Base(_Logger, _Config): pass


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
# endregion
