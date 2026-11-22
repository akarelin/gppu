# .. archived 2026-11-22: what gppu's reduction removed from tests/test_diskcache.py, as it was last


# .. from fec31bb
class TestCacheDiskcache:
    """Tests specifically for the diskcache backend."""

    @pytest.fixture(autouse=True)
    def _require_diskcache(self):
        pytest.importorskip('diskcache')

    def test_roundtrip(self, tmp_path):
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend='diskcache', skip_env='')
        cache.set('key', 'value')
        assert cache.get('key') == 'value'
        cache.close()


class TestCache:
  # .. from fec31bb
    def test_skip_via_env(self, tmp_path, backend, monkeypatch):
        monkeypatch.setenv('TEST_SKIP', 'true')
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend, skip_env='TEST_SKIP')
        assert cache.skip is True
        cache.set('key', 'value')
        assert cache.get('key') is None
        cache.close()

  # .. from fec31bb
    def test_skip_not_active(self, tmp_path, backend, monkeypatch):
        monkeypatch.delenv('SKIP_CACHE', raising=False)
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend)
        assert cache.skip is False
        cache.close()

  # .. from fec31bb
    def test_decorator_skip_bypasses(self, tmp_path, backend, monkeypatch):
        monkeypatch.setenv('TEST_SKIP', 'true')
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend, skip_env='TEST_SKIP')
        call_count = 0

        @cache
        def expensive(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert expensive(5) == 10
        assert expensive(5) == 10
        assert call_count == 2
        cache.close()

  # .. from gppu/v3.7.9
    def test_graceful_after_close(self, tmp_path, backend):
        cache = Cache(str(tmp_path / 'cache'), ttl=60, backend=backend, skip_env='')
        cache.set('key', 'value')
        cache.close()
        assert cache.get('key', 'fallback') == 'fallback'
