"""gppu.data — databases and local persistence: PostgreSQL through psycopg2.

Replaces _PersistentBase, _PGBase and _SQABase: an app no longer inherits a database, it asks for one.

    connections:
      pg-lake: {provider: gppu.data.Postgres, dsn: !secret pg-lake-dsn}

    class Count(CliApp):
      def main(self, db: Postgres = 'pg-lake') -> int:
        return db.scalar('select count(*) from files.lake')
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from gppu import Provider


class Postgres(Provider):
  """One PostgreSQL database. Connects on first use; a cursor commits on success and rolls back on error."""
  scheme = 'postgres'

  def __init__(self, connection=None, uid: str = '') -> None:
    super().__init__(connection, uid)
    self._db = None

  @property
  def db(self):
    if self._db is None:
      import psycopg2
      self._db = psycopg2.connect(self.connection['dsn'])
    return self._db

  @contextmanager
  def cursor(self) -> Iterator[Any]:
    from psycopg2.extras import RealDictCursor
    cur = self.db.cursor(cursor_factory=RealDictCursor)
    try:
      yield cur
      self.db.commit()
    except Exception:
      self.db.rollback()
      raise
    finally: cur.close()

  def rows(self, sql: str, *args: Any) -> list[dict]:
    with self.cursor() as cur:
      cur.execute(sql, args)
      return cur.fetchall()

  def scalar(self, sql: str, *args: Any) -> Any:
    with self.cursor() as cur:
      cur.execute(sql, args)
      return next(iter(cur.fetchone().values()))

  def close(self) -> None:
    if self._db is not None: self._db.close()
    self._db = None
