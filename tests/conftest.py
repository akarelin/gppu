"""Shared fixtures for gppu tests."""
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

# Add repo root to path for direct execution (without pip install -e)
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture(autouse=True)
def one_gppufs_per_test():
    """gppufs is one object in a process; each test starts with its own, as a new process does."""
    from gppu.fs.gppufs import GppuFileSystem, _INDEXES
    GppuFileSystem.clear_instance_cache()
    _INDEXES.clear()
    yield


@pytest.fixture(scope='module')
def ld():
    """Linked Data's fs API, the catalog's database, on a database made for a module's tests from gppu.ld's SQL (ld.sql) on the
    Postgres server LD_TEST_DSN names, and dropped after them, as test_ld.py makes its own; the tests that need it are skipped
    without it."""
    dsn = os.environ.get('LD_TEST_DSN')
    if not dsn:
        pytest.skip('LD_TEST_DSN, the Postgres the catalog tests make their database on, is not set')
    import psycopg
    from fastapi.testclient import TestClient
    from gppu import Env
    from gppu.data import _SQABase
    from gppu.fs import files
    from gppu.ld import serve
    db = f'gppu_catalog_test_{uuid4().hex[:12]}'   # its own, so no other database on the server is touched
    with psycopg.connect(dsn, autocommit=True) as server:
        server.execute(f'CREATE DATABASE {db}')
    previous, initialized = Env.data, Env.initialized
    try:
        store = dsn.rsplit('/', 1)[0] + '/' + db
        with psycopg.connect(store, autocommit=True) as made:
            made.execute((Path(__file__).parent / 'ld.sql').read_text(encoding='utf-8'))
        Env._load_dict({'db': store})
        with TestClient(serve({'/fs': files.app}, _SQABase()), backend_options={'loop_factory': asyncio.SelectorEventLoop}) as client:
            yield client
    finally:
        Env.reset()
        Env.data, Env.initialized = previous, initialized
        with psycopg.connect(dsn, autocommit=True) as server:
            server.execute(f'DROP DATABASE {db} WITH (FORCE)')
