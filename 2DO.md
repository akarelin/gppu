# gppu — 2Do

## data / cache

### Eliminate the two extra cache implementations

`gppu.data.Cache` (`gppu/data.py:317`) is the canonical key/value+TTL store
with five backends. Two other places re-implement bits of cache logic
on top of it:

1. `gppu/tui/cache.py` — `CachedFetcher`, `PaginatedFetcher` are pure
   read-through wrappers (130 LOC) with no Textual dependency. Only
   `CacheRefreshMixin` (35 LOC) is genuinely TUI. Move the fetchers into
   `gppu.data` next to `Cache`; leave the mixin in `gppu.tui`.
2. `statusline/cache.py` — wraps `gppu.data.Cache` with JSONL-incremental
   + git-TTL helpers specific to the Claude Code statusline. The pieces
   that aren't statusline-specific (TTL routing, JSONL append) belong in
   `gppu.data`; the rest stays.

End state: one `gppu.data` module that owns all cache code, and one
small `CacheRefreshMixin` in `gppu.tui` that's actually about TUI.
