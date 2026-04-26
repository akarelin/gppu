"""Cache ↔ TUI wiring — read-through fetchers with force-refresh.

``gppu.data.Cache`` already handles the key/value/TTL storage.  This
module adds the missing glue between cache and TUI:

- :class:`CachedFetcher` — wraps a raw fetch function, returns cached
  value if live, falls through to the fetch on miss, writes back.
- :class:`PaginatedFetcher` — same semantics for page-at-a-time APIs.
  Each page is cached separately so partial-page invalidation works.
- :class:`CacheRefreshMixin` — adds ``action_refresh`` + ``R`` binding
  that bypasses cache on next call.

Lifted from SessionManager (``A/SessionManager/scripts/sm-tui.py:70-145``),
where ``api_get`` / ``api_get_paginated`` re-implement exactly this
pattern every time.  The goal: any app that talks to Langfuse / Linear /
GitHub / whatever pageable API can set up a cache-backed TUI in about
six lines.

Example::

    from gppu.data import Cache
    from gppu.tui import CachedFetcher, PaginatedFetcher, CacheRefreshMixin

    cache = Cache('~/.cache/myapp', ttl=600, backend='sqlite')

    get_items = CachedFetcher(
        cache=cache,
        fetch=lambda **params: requests.get(URL, params=params).json(),
        key_fn=lambda **params: f"GET:{URL}:{sorted(params.items())}",
    )

    class MyApp(CacheRefreshMixin, LoaderMixin, TUIApp):
        CACHE_INSTANCE = cache

        def on_mount(self):
            self.load_async(
                fetch=lambda: get_items(limit=100),
                on_done=self._populate,
            )

Press ``R`` in the TUI → next fetch bypasses the cache for one call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


# ── fetchers ───────────────────────────────────────────────────────────────

@dataclass
class CachedFetcher:
    """Read-through wrapper: cache.get → fetch → cache.set.

    The wrapped ``fetch`` callable is invoked **only on miss or when the
    caller sets** ``use_cache=False``.  Bypass is also automatic when the
    underlying ``Cache.skip`` is True (e.g. ``SKIP_CACHE=1`` env var set).

    ``key_fn`` must return a stable string for each unique param set.  If
    omitted, a deterministic tuple-based key is used — sufficient for
    most keyword-arg call shapes.
    """
    cache: Any                                   # gppu.data.Cache
    fetch: Callable[..., Any]
    key_fn: Callable[..., str] | None = None
    ttl: int | None = None                       # None → use cache default

    def __call__(self, *args: Any, use_cache: bool = True, **kwargs: Any) -> Any:
        key = self._key(args, kwargs)
        if use_cache and not self.cache.skip:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        try:
            value = self.fetch(*args, **kwargs)
        except Exception:
            raise
        if use_cache and not self.cache.skip and value is not None:
            self.cache.set(key, value, ttl=self.ttl)
        return value

    def _key(self, args: tuple, kwargs: dict) -> str:
        if self.key_fn:
            return self.key_fn(*args, **kwargs)
        return f'{self.fetch.__name__}:{args}:{tuple(sorted(kwargs.items()))}'


@dataclass
class PaginatedFetcher:
    """Cache-aware paginator — each page cached separately.

    ``fetch_page(page, limit, **params) -> dict`` is the caller-supplied
    single-page loader.  It must return a dict with ``'data'`` (list of
    items) and optionally ``'meta' or 'total'`` (for completion and
    totalItems count).  :meth:`__call__` returns ``(all_items, total)``.

    Partial invalidation: drop one page by ``cache.delete(key)`` without
    flushing the others.  Force-refresh all pages by calling with
    ``use_cache=False``.
    """
    cache: Any
    fetch_page: Callable[..., dict]
    key_fn: Callable[..., str]                   # must include page number
    max_pages: int = 10
    limit: int = 100
    total_from: Callable[[dict], int] = field(
        default=lambda d: int(
            (d.get('meta') or {}).get('totalItems', 0)
            or d.get('total', 0)
            or 0
        )
    )

    def __call__(self, *, use_cache: bool = True, **params: Any) -> tuple[list, int]:
        out: list = []
        total = 0
        for page in range(1, self.max_pages + 1):
            key = self.key_fn(page=page, limit=self.limit, **params)
            data: dict | None = None
            if use_cache and not self.cache.skip:
                data = self.cache.get(key)
            if data is None:
                data = self.fetch_page(page=page, limit=self.limit, **params) or {}
                if use_cache and not self.cache.skip:
                    self.cache.set(key, data)
            rows = data.get('data', []) or []
            if not rows:
                break
            out.extend(rows)
            total = max(total, self.total_from(data))
            if len(rows) < self.limit:
                break
        return out, (total or len(out))


# ── Textual mixin ──────────────────────────────────────────────────────────

try:
    from textual.binding import Binding
    _TEXTUAL = True
except ImportError:
    _TEXTUAL = False


if _TEXTUAL:

    class CacheRefreshMixin:
        """Mixin that adds an ``R`` keybinding → "reload bypassing cache".

        Apps set ``CACHE_INSTANCE`` to a ``gppu.data.Cache`` and override
        ``cache_refresh()`` with their own reload routine (typically the
        same method ``on_mount`` calls, but with ``use_cache=False``).

            class MyApp(CacheRefreshMixin, TUIApp):
                CACHE_INSTANCE = my_cache
                BINDINGS = [*CacheRefreshMixin.CACHE_BINDINGS, ...]

                def cache_refresh(self):
                    self.load_async(fetch=lambda: my_fetcher(use_cache=False),
                                    on_done=self._populate)
        """

        CACHE_BINDINGS = [
            Binding('R', 'cache_refresh', 'Refresh (skip cache)', show=False),
        ]

        CACHE_INSTANCE: Any = None

        def cache_refresh(self) -> None:
            """Override in subclass.  Default: notify "not implemented"."""
            try:
                self.notify('cache_refresh() not implemented on this app',
                            severity='warning', timeout=3)
            except Exception:
                pass

        def action_cache_refresh(self) -> None:
            self.cache_refresh()

else:
    CacheRefreshMixin = None  # type: ignore[assignment]
