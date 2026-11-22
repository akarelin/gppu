"""Tests for Cache."""
import time

import pytest

from gppu.data import Cache


class TestCache:
    @pytest.fixture(params=['json', 'pickle', 'sqlite'])
    def backend(self, request):
        return request.param

    def test_set_get_roundtrip(self, tmp_path, backend):
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend)
        cache.set('key', {'a': 1, 'b': [2, 3]})
        assert cache.get('key') == {'a': 1, 'b': [2, 3]}
        cache.close()

    def test_get_miss_returns_default(self, tmp_path, backend):
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend)
        assert cache.get('missing') is None
        assert cache.get('missing', 42) == 42
        cache.close()

    def test_ttl_expiration(self, tmp_path, backend):
        cache = Cache(str(tmp_path / 'cache'), ttl=1, backend=backend)
        cache.set('key', 'value')
        assert cache.get('key') == 'value'
        time.sleep(2)
        assert cache.get('key') is None
        cache.close()

    def test_per_key_ttl_override(self, tmp_path, backend):
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend)
        cache.set('short', 'val', ttl=1)
        cache.set('long', 'val', ttl=60)
        time.sleep(2)
        assert cache.get('short') is None
        assert cache.get('long') == 'val'
        cache.close()

    def test_delete(self, tmp_path, backend):
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend)
        cache.set('key', 'value')
        cache.delete('key')
        assert cache.get('key') is None
        cache.close()

    def test_a_closed_cache_raises(self, tmp_path, backend):
        # .. a failure of the backend reaches the caller: nothing turns it into the default
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend)
        cache.set('key', 'value')
        cache.close()
        with pytest.raises(AttributeError): cache.get('key', 'fallback')

    def test_context_manager(self, tmp_path, backend):
        with Cache(str(tmp_path / 'cache'), ttl=60, backend=backend) as cache:
            cache.set('key', 'value')
            assert cache.get('key') == 'value'
        assert cache._cache is None

    def test_decorator_memoizes(self, tmp_path, backend):
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend)
        call_count = 0

        @cache
        def expensive(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert expensive(5) == 10
        assert expensive(5) == 10
        assert call_count == 1
        assert expensive(3) == 6
        assert call_count == 2
        cache.close()

    def test_invalid_backend_raises(self, tmp_path):
        with pytest.raises(ValueError, match='Unknown backend'):
            Cache(str(tmp_path / 'cache'), backend='nope')

