"""gppu.data — provider: local persistence. From gppu/data.py, Cache and Persistence keep their json, sqlite and
pickle backends; the diskcache and database backends go with gppu.postgres or are dropped (see README).
_PersistentBase, _PGBase and _SQABase are replaced by gppu.postgres.Postgres; _PersistentDC has no user."""
