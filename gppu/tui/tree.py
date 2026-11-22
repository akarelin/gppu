"""The entries a hierarchy's view lists, and the adapter that gives them.

- :class:`TreeEntry` is one node of the hierarchy.
- :class:`TreeAdapter` is the protocol a data source implements: its root, and the children of an entry, on expansion.

:class:`gppu.tui.TreeTable` shows a hierarchy through an adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable


# .. ── adapter protocol + data record ────────────────────────────────────────

@dataclass
class TreeEntry:
    """One node's worth of information for a hierarchy's view.

    ``id`` is a stable identifier the adapter understands (absolute path,
    Drive folder id, bucket key …).  ``meta`` is free-form — adapters can
    stash sizes, mtimes, icons, MIME types here for renderers to use.
    """
    id: str
    label: str
    is_container: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TreeAdapter(Protocol):
    """Data source for :class:`TreeTable`.

    Implement ``root`` (single seed) and ``children`` (lazy expansion).
    Both run on the MAIN thread by default — wrap I/O in the caller's
    ``LoaderMixin.load_async`` if latency is a concern.
    """

    def root(self) -> TreeEntry: ...
    def children(self, entry: TreeEntry) -> Iterable[TreeEntry]: ...
