"""Tests for DiskCache."""
import time

import pytest

diskcache = pytest.importorskip('diskcache')

from gppu.data import DiskCache


class TestDiskCache:
    def test_set_get_roundtrip(self, tmp_path):
        cache = DiskCache(str(tmp_path / 'cache'), ttl=60, skip_env='')
        cache.set('key', {'a': 1, 'b': [2, 3]})
        assert cache.get('key') == {'a': 1, 'b': [2, 3]}
        cache.close()

    def test_get_miss_returns_default(self, tmp_path):
        cache = DiskCache(str(tmp_path / 'cache'), ttl=60, skip_env='')
        assert cache.get('missing') is None
        assert cache.get('missing', 42) == 42
        cache.close()

    def test_ttl_expiration(self, tmp_path):
        cache = DiskCache(str(tmp_path / 'cache'), ttl=1, skip_env='')
        cache.set('key', 'value')
        assert cache.get('key') == 'value'
        time.sleep(2)
        assert cache.get('key') is None
        cache.close()

    def test_per_key_ttl_override(self, tmp_path):
        cache = DiskCache(str(tmp_path / 'cache'), ttl=60, skip_env='')
        cache.set('short', 'val', ttl=1)
        cache.set('long', 'val', ttl=60)
        time.sleep(2)
        assert cache.get('short') is None
        assert cache.get('long') == 'val'
        cache.close()

    def test_delete(self, tmp_path):
        cache = DiskCache(str(tmp_path / 'cache'), ttl=60, skip_env='')
        cache.set('key', 'value')
        cache.delete('key')
        assert cache.get('key') is None
        cache.close()

    def test_skip_via_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv('TEST_SKIP', 'true')
        cache = DiskCache(str(tmp_path / 'cache'), ttl=60, skip_env='TEST_SKIP')
        assert cache.skip is True
        cache.set('key', 'value')
        assert cache.get('key') is None
        cache.close()

    def test_skip_not_active(self, tmp_path, monkeypatch):
        monkeypatch.delenv('SKIP_CACHE', raising=False)
        cache = DiskCache(str(tmp_path / 'cache'), ttl=60)
        assert cache.skip is False
        cache.close()

    def test_graceful_after_close(self, tmp_path):
        cache = DiskCache(str(tmp_path / 'cache'), ttl=60, skip_env='')
        cache.set('key', 'value')
        cache.close()
        assert cache.get('key', 'fallback') == 'fallback'

    def test_context_manager(self, tmp_path):
        with DiskCache(str(tmp_path / 'cache'), ttl=60, skip_env='') as cache:
            cache.set('key', 'value')
            assert cache.get('key') == 'value'
        assert cache._cache is None
