<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/cache.py f347d91282af43277f73427367313793af8c9764 -->
`gppu.tui.cache` connects `gppu.data.Cache` to Textual TUI apps. It wraps the calls that load data from an API so that the TUI reads from the cache, and it gives the user a key that reloads the data past the cache.

The module has three parts that share one `Cache` instance.

`CachedFetcher` wraps one fetch function. A call asks the cache for its key first. On a hit it returns the stored value. On a miss it calls the wrapped function and stores the result, unless the result is `None`. The key comes from `key_fn` if you pass one. Otherwise it is built from the fetch function's name, the positional arguments and the sorted keyword arguments. Both fetchers bypass the cache while `cache.skip` is true.

`PaginatedFetcher` does the same for an API that returns one page at a time. Each page is cached under its own key, so you can drop one page with `cache.delete` and leave the rest. The caller's `fetch_page` returns a dict whose `data` list holds the items. The total comes from `meta.totalItems` or `total`, through `total_from`. Fetching stops at `max_pages`, at an empty page, or at a page shorter than `limit`. The call returns `(items, total)`, and when no total is reported, the total is the number of items fetched. `key_fn` must include the page number. `PaginatedFetcher` has no TTL setting of its own.

`CacheRefreshMixin` adds the `R` key to a Textual app. The app must add `CACHE_BINDINGS` to its `BINDINGS`. Pressing `R` calls `cache_refresh()`. The default `cache_refresh()` only shows a warning, so the app overrides it to reload with `use_cache=False`. The mixin declares `CACHE_INSTANCE`, but the module never reads it. The mixin exists only when Textual is installed; otherwise `CacheRefreshMixin` is `None`.

A program sets up a cache, wraps its fetch function, and calls the wrapped function from its app:

```python
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
    BINDINGS = [*CacheRefreshMixin.CACHE_BINDINGS]

    def on_mount(self):
        self.load_async(
            fetch=lambda: get_items(limit=100),
            on_done=self._populate,
        )

    def cache_refresh(self):
        self.load_async(
            fetch=lambda: get_items(limit=100, use_cache=False),
            on_done=self._populate,
        )
```

`requests`, `URL`, `LoaderMixin` and `TUIApp` come from the program and are not defined in this module.
