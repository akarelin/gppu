"""Tests for gppu.tui.cache — CachedFetcher + PaginatedFetcher.

The underlying ``gppu.data.Cache`` is covered separately.  Here we only
verify the TUI-facing wiring: cache-hit, cache-miss + write, bypass,
pagination + completion conditions.
"""
from __future__ import annotations

import pytest

from gppu.tui.cache import CachedFetcher, PaginatedFetcher


class _FakeCache:
    """Minimal in-memory cache mimicking gppu.data.Cache's public surface."""

    def __init__(self, skip: bool = False):
        self.skip = skip
        self._d: dict = {}

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value, ttl=None):
        self._d[key] = value

    def delete(self, key):
        self._d.pop(key, None)


# ── CachedFetcher ─────────────────────────────────────────────────────────

class TestCachedFetcher:
    def test_miss_then_hit(self):
        calls = []
        def fetch_fn(x):
            calls.append(x)
            return x * 10
        f = CachedFetcher(cache=_FakeCache(), fetch=fetch_fn,
                          key_fn=lambda x: f'k:{x}')
        assert f(3) == 30 and len(calls) == 1
        # second call hits cache, no extra fetch
        assert f(3) == 30 and len(calls) == 1

    def test_use_cache_false_bypasses(self):
        calls = []
        f = CachedFetcher(
            cache=_FakeCache(),
            fetch=lambda x: (calls.append(x), x + 1)[1],
            key_fn=lambda x: f'k:{x}',
        )
        f(1)
        f(1, use_cache=False)
        assert len(calls) == 2

    def test_skip_env_disables_cache(self):
        """When the Cache reports skip=True, bypass is automatic."""
        calls = []
        f = CachedFetcher(
            cache=_FakeCache(skip=True),
            fetch=lambda x: (calls.append(x), 1)[1],
            key_fn=lambda x: f'k:{x}',
        )
        f(42); f(42); f(42)
        assert len(calls) == 3

    def test_default_key_fn_when_omitted(self):
        f = CachedFetcher(cache=_FakeCache(),
                          fetch=lambda a, b: a + b)
        assert f(1, 2) == 3
        # Same inputs → same key → cache hit second call (verified by no extra side-effect)
        side_effects = []
        f2 = CachedFetcher(
            cache=_FakeCache(),
            fetch=lambda a, b: (side_effects.append((a, b)), a + b)[1],
        )
        f2(1, 2); f2(1, 2)
        assert len(side_effects) == 1

    def test_none_result_not_cached(self):
        """A None fetch result should not poison the cache."""
        calls = []
        def fetch_fn():
            calls.append(1)
            return None
        f = CachedFetcher(cache=_FakeCache(), fetch=fetch_fn,
                          key_fn=lambda: 'k')
        f(); f()
        assert len(calls) == 2


# ── PaginatedFetcher ──────────────────────────────────────────────────────

class TestPaginatedFetcher:
    def test_fetches_and_aggregates(self):
        # 3 pages of 10 items each, then empty
        def fetch_page(*, page, limit, **_):
            if page > 3:
                return {'data': [], 'meta': {'totalItems': 25}}
            return {'data': list(range(limit)), 'meta': {'totalItems': 25}}
        pf = PaginatedFetcher(
            cache=_FakeCache(),
            fetch_page=fetch_page,
            key_fn=lambda *, page, limit, **_: f'p:{page}:{limit}',
            max_pages=5, limit=10,
        )
        rows, total = pf()
        # stops when a page returns fewer than `limit` rows — but all pages
        # here return exactly `limit` until an empty page
        assert total == 25
        assert len(rows) == 30      # 3 pages × 10 items

    def test_short_page_stops_early(self):
        def fetch_page(*, page, limit, **_):
            return {'data': list(range(3))}   # only 3 < limit=10
        pf = PaginatedFetcher(
            cache=_FakeCache(),
            fetch_page=fetch_page,
            key_fn=lambda *, page, limit, **_: f'p:{page}',
            max_pages=10, limit=10,
        )
        rows, total = pf()
        assert len(rows) == 3
        # total falls back to len(rows) when meta has no totalItems
        assert total == 3

    def test_max_pages_bounds(self):
        def fetch_page(*, page, limit, **_):
            return {'data': list(range(limit))}   # infinite
        pf = PaginatedFetcher(
            cache=_FakeCache(),
            fetch_page=fetch_page,
            key_fn=lambda *, page, limit, **_: f'p:{page}',
            max_pages=2, limit=5,
        )
        rows, _ = pf()
        assert len(rows) == 10    # max_pages × limit

    def test_per_page_caching(self):
        cache = _FakeCache()
        calls = []
        def fetch_page(*, page, limit, **_):
            calls.append(page)
            return {'data': list(range(limit))} if page <= 2 else {'data': []}
        pf = PaginatedFetcher(
            cache=cache, fetch_page=fetch_page,
            key_fn=lambda *, page, limit, **_: f'p:{page}',
            max_pages=3, limit=4,
        )
        # First run: fetches pages 1, 2, 3
        pf()
        assert calls == [1, 2, 3]
        # Second run: all cached — no new fetches
        pf()
        assert calls == [1, 2, 3]
        # Bypass one page by deleting its cache entry
        cache.delete('p:2')
        pf()
        # Only page 2 should re-fetch; 1 and 3 remain cached
        assert calls == [1, 2, 3, 2]

    def test_bypass(self):
        cache = _FakeCache()
        calls = []
        def fetch_page(*, page, limit, **_):
            calls.append(page)
            return {'data': list(range(limit))} if page == 1 else {'data': []}
        pf = PaginatedFetcher(
            cache=cache, fetch_page=fetch_page,
            key_fn=lambda *, page, limit, **_: f'p:{page}',
            max_pages=2, limit=3,
        )
        pf()                # fills cache
        pf(use_cache=False) # bypass
        # Each run does its own fetches
        assert calls.count(1) == 2
