# .. archived 2026-11-22: what gppu's reduction removed from gppu/data.py, as it was last


# .. from fec31bb
class _PersistentDC(_DC):
  """_DC subclass that persists self.data through a pluggable backend.

  Storage is namespaced by (type(self).__name__, self.data[_persist_key]).
  Subclasses wanting custom storage override _do_persist() / load().

  Backend protocol (duck-typed; see `gppu.data.Persistence` for the standard
  factory and built-in backends: json, pickle, sqlite, postgres):
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


# .. from fec31bb
class _DiskcacheBackend:
  """diskcache backend. Requires: pip install diskcache"""

  def __init__(self, path: str):
    from diskcache import Cache
    self._cache = Cache(path)

  def get(self, key: str, default=None): return self._cache.get(key, default)
  def set(self, key: str, value, expire=None): self._cache.set(key, value, expire=expire)
  def delete(self, key: str): self._cache.delete(key)
  def close(self): self._cache.close(); self._cache = None


# .. from fec31bb
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


# .. from fec31bb
DiskCache = None  # .. removed, use Cache


# .. from fec31bb
class _FilePersistBackend:
  """File backend: one file, nested dict {cls: {key: data}}, json or pickle as its serializer. No deps."""

  def __init__(self, path: str, serializer, name: str):
    import os
    self._serializer, self._binary = serializer, serializer is pickle
    self._path = path
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path): self._path = os.path.join(path, name)
    self._data: dict[str, dict[str, dict]] = {}
    try:
      with open(self._path, 'rb' if self._binary else 'r') as f: self._data = self._serializer.load(f)
    except Exception: pass

  def _flush(self):
    with open(self._path, 'wb' if self._binary else 'w') as f: self._serializer.dump(self._data, f)

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


# .. from fec31bb
class _SqlitePersistBackend:
  """SQLite backend. One file, one table `persistent_dc(cls, key, data)`. Stdlib only."""

  def __init__(self, path: str):
    import os, sqlite3, threading
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path): path = os.path.join(path, '_persist.db')
    self._conn = sqlite3.connect(path, check_same_thread=False)
    self._lock = threading.Lock()
    self._conn.execute(
      'CREATE TABLE IF NOT EXISTS persistent_dc '
      '(cls TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, '
      ' updated_at REAL NOT NULL, PRIMARY KEY (cls, key))')
    self._conn.commit()

  def upsert(self, cls: str, key: str, data: dict) -> None:
    import json, time
    with self._lock:
      self._conn.execute(
        'INSERT OR REPLACE INTO persistent_dc (cls, key, data, updated_at) VALUES (?, ?, ?, ?)',
        (cls, key, json.dumps(data), time.time()))
      self._conn.commit()

  def load(self, cls: str, key: str) -> Optional[dict]:
    import json
    with self._lock:
      row = self._conn.execute(
        'SELECT data FROM persistent_dc WHERE cls=? AND key=?', (cls, key)).fetchone()
    return json.loads(row[0]) if row else None

  def iter(self, cls: str):
    import json
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


# .. from fec31bb
class _PgPersistBackend(_PGBase):
  """Postgres backend (psycopg2). Table `persistent_dc(cls, key, data JSONB, updated_at)`."""

  SCHEMA_DDL = """
  CREATE TABLE IF NOT EXISTS persistent_dc (
    cls         TEXT NOT NULL,
    key         TEXT NOT NULL,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cls, key)
  );
  CREATE INDEX IF NOT EXISTS persistent_dc_cls_idx ON persistent_dc (cls);
  """

  def __init__(self, **kw):
    super().__init__(**kw)
    import threading
    self._lock = threading.Lock()
    with self._lock, self.cursor(dict_cursor=False) as cur:
      cur.execute(self.SCHEMA_DDL)

  def upsert(self, cls: str, key: str, data: dict) -> None:
    from psycopg2.extras import Json
    with self._lock, self.cursor(dict_cursor=False) as cur:
      cur.execute(
        "INSERT INTO persistent_dc (cls, key, data, updated_at) "
        "VALUES (%s, %s, %s, now()) "
        "ON CONFLICT (cls, key) DO UPDATE SET "
        "  data=EXCLUDED.data, updated_at=now()",
        (cls, key, Json(data)))

  def load(self, cls: str, key: str) -> Optional[dict]:
    with self._lock, self.cursor() as cur:
      cur.execute(
        "SELECT data FROM persistent_dc WHERE cls=%s AND key=%s", (cls, key))
      row = cur.fetchone()
    return dict(row['data']) if row else None

  def iter(self, cls: str):
    with self._lock, self.cursor() as cur:
      cur.execute(
        "SELECT key, data FROM persistent_dc WHERE cls=%s ORDER BY key", (cls,))
      rows = cur.fetchall()
    for r in rows: yield r['key'], dict(r['data'])

  def delete(self, cls: str, key: str) -> None:
    with self._lock, self.cursor(dict_cursor=False) as cur:
      cur.execute("DELETE FROM persistent_dc WHERE cls=%s AND key=%s", (cls, key))


# .. from fec31bb
_PERSIST_BACKENDS = {
  'json':     lambda path: _FilePersistBackend(path, json, '_persist.json'),
  'pickle':   lambda path: _FilePersistBackend(path, pickle, '_persist.pkl'),
  'sqlite':   _SqlitePersistBackend,
  'postgres': _PgPersistBackend,
}


# .. from fec31bb
class Persistence:
  """Storage for `_PersistentDC` instances, multi-backend.

  Mirrors the `Cache` class shape.

  Backends (explicit, no fallback):
    json      — JSON file, no deps
    pickle    — pickle file, no deps
    sqlite    — stdlib sqlite3
    postgres  — psycopg2 + JSONB; takes a connection string (db kwarg)

  Usage:
    p = Persistence('/var/lib/y2/persist.db', backend='sqlite')
    p = Persistence('postgresql://...', backend='postgres')   # target is the DSN

    _PersistentDC.bind_db(p)
  """

  def __init__(self, target: str, *, backend: str = 'sqlite'):
    import os
    if backend not in _PERSIST_BACKENDS:
      raise ValueError(f"Unknown backend {backend!r}, expected one of: {', '.join(_PERSIST_BACKENDS)}")
    if backend == 'postgres':
      self._b = _PgPersistBackend(db=target)
    else:
      self._b = _PERSIST_BACKENDS[backend](os.path.expanduser(target))

  def upsert(self, cls: str, key: str, data: dict) -> None: self._b.upsert(cls, key, data)
  def load(self, cls: str, key: str) -> Optional[dict]: return self._b.load(cls, key)
  def iter(self, cls: str): yield from self._b.iter(cls)
  def delete(self, cls: str, key: str) -> None: self._b.delete(cls, key)
  def close(self):
    if self._b: self._b.close(); self._b = None  # type: ignore[assignment]

  def __enter__(self): return self
  def __exit__(self, *_): self.close()


# .. from gppu/v3.7.9
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


# .. from gppu/v3.7.9
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


# .. from gppu/v3.7.9
class _JsonPersistBackend:
  """JSON-file backend. One file, nested dict {cls: {key: data}}. No deps."""

  def __init__(self, path: str):
    import os, json
    self._path = path
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path): self._path = os.path.join(path, '_persist.json')
    self._data: dict[str, dict[str, dict]] = {}
    try:
      with open(self._path) as f: self._data = json.load(f)
    except Exception: pass

  def _flush(self):
    import json
    with open(self._path, 'w') as f: json.dump(self._data, f)

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


# .. from gppu/v3.7.9
class _PicklePersistBackend:
  """Pickle-file backend. Same shape as _JsonPersistBackend. No deps."""

  def __init__(self, path: str):
    import os, pickle
    self._path = path
    os.makedirs(os.path.dirname(path) if not os.path.isdir(path) else path, exist_ok=True)
    if os.path.isdir(path): self._path = os.path.join(path, '_persist.pkl')
    self._data: dict[str, dict[str, dict]] = {}
    try:
      with open(self._path, 'rb') as f: self._data = pickle.load(f)
    except Exception: pass

  def _flush(self):
    import pickle
    with open(self._path, 'wb') as f: pickle.dump(self._data, f)

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


class Cache:
  # .. from fec31bb
  @property
  def skip(self) -> bool: return self._skip
