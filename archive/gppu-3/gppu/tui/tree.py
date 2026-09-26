"""Generic tree browser — ``Tree`` widget with swappable data adapters.

Lets any app build a browse-and-select UI over a hierarchical data source
(local filesystem, Google Drive, S3 bucket, vault tree, Obsidian vault,
config tree …) without re-inventing lazy-load, expansion state, and the
async fetch dance every time.

Two pieces:

- :class:`TreeAdapter` — protocol the caller implements for their data
  source.  Must yield :class:`TreeEntry` records.
- :class:`TreeBrowser` — ``Tree`` subclass.  Handles compose, lazy
  expansion, placeholders, and a caller-facing ``on_entry_selected``
  message so the app can react without subclassing.

Bundled adapters:

- :class:`FilesystemAdapter` — walks local directories.  Novel; no other
  app in the workspace does this today.
- :class:`GDriveAdapter` — placeholder import-safe class; the real Google
  Drive client lives in caller code (see
  ``CRAP/CRAP/GD-Video-Ripper/drive_browser.py`` for the shape).
  Implement by passing a pre-built Drive ``service`` to the ctor.

Example — filesystem::

    from gppu.tui import TreeBrowser, FilesystemAdapter

    class MyApp(TUIApp):
        def compose(self):
            yield TreeBrowser(
                adapter=FilesystemAdapter('~/CRAP', show_hidden=False),
                id='fs-tree',
            )

        def on_tree_browser_entry_selected(self, event):
            path = event.entry.id
            self.log_write(f'selected: {path}')
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable

from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode


# ── adapter protocol + data record ────────────────────────────────────────

@dataclass
class TreeEntry:
    """One node's worth of information for the generic tree browser.

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
    """Data source for :class:`TreeBrowser`.

    Implement ``root`` (single seed) and ``children`` (lazy expansion).
    Both run on the MAIN thread by default — wrap I/O in the caller's
    ``LoaderMixin.load_async`` if latency is a concern.
    """

    def root(self) -> TreeEntry: ...
    def children(self, entry: TreeEntry) -> Iterable[TreeEntry]: ...


# ── bundled adapters ──────────────────────────────────────────────────────

@dataclass
class FilesystemAdapter:
    """Walks the local filesystem.

    ``root_path`` is expanded (``~``) and normalized once at construct
    time.  ``show_hidden`` toggles dotfiles.  ``max_depth`` caps
    recursion — the browser still lazy-loads, this is a safety net.
    """
    root_path: str
    show_hidden: bool = False
    max_depth: int | None = None

    def __post_init__(self):
        self.root_path = os.path.abspath(os.path.expanduser(self.root_path))

    def root(self) -> TreeEntry:
        label = self.root_path
        return TreeEntry(
            id=self.root_path,
            label=label,
            is_container=os.path.isdir(self.root_path),
            meta={'depth': 0},
        )

    def children(self, entry: TreeEntry) -> Iterable[TreeEntry]:
        if not entry.is_container:
            return []
        depth = entry.meta.get('depth', 0)
        if self.max_depth is not None and depth >= self.max_depth:
            return []
        try:
            names = sorted(os.listdir(entry.id))
        except OSError:
            return []
        out: list[TreeEntry] = []
        for name in names:
            if not self.show_hidden and name.startswith('.'):
                continue
            full = os.path.join(entry.id, name)
            try:
                is_dir = os.path.isdir(full)
                size = os.path.getsize(full) if not is_dir else 0
            except OSError:
                continue
            out.append(TreeEntry(
                id=full,
                label=name + ('/' if is_dir else ''),
                is_container=is_dir,
                meta={'depth': depth + 1, 'size': size},
            ))
        # Directories first, then files — conventional FS display.
        out.sort(key=lambda e: (not e.is_container, e.label.lower()))
        return out


@dataclass
class GDriveAdapter:
    """Google-Drive tree adapter.

    Caller supplies a pre-authenticated Google Drive ``service`` object
    (``googleapiclient.discovery.build('drive', 'v3', ...)``).  This
    keeps gppu free of Google SDK dependencies.

    Based on the shape in ``CRAP/CRAP/GD-Video-Ripper/drive_browser.py`` —
    queries are ``mimeType='application/vnd.google-apps.folder'`` to
    enumerate folders, then the caller's own code populates whatever
    content pane they're driving (this adapter only handles the tree).
    """
    service: Any                                   # googleapiclient service
    root_id: str = 'root'
    root_label: str = 'My Drive'
    page_size: int = 200

    def root(self) -> TreeEntry:
        return TreeEntry(
            id=self.root_id,
            label=self.root_label,
            is_container=True,
            meta={},
        )

    def children(self, entry: TreeEntry) -> Iterable[TreeEntry]:
        if not entry.is_container:
            return []
        q = (
            f"'{entry.id}' in parents and "
            "mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        out: list[TreeEntry] = []
        page_token = None
        while True:
            params = {
                'pageSize': self.page_size,
                'q': q,
                'fields': 'nextPageToken, files(id,name,modifiedTime)',
            }
            if page_token:
                params['pageToken'] = page_token
            try:
                resp = self.service.files().list(**params).execute()
            except Exception:
                break
            for f in resp.get('files', []):
                out.append(TreeEntry(
                    id=f['id'],
                    label=f['name'],
                    is_container=True,
                    meta={'modifiedTime': f.get('modifiedTime', '')},
                ))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        out.sort(key=lambda e: e.label.lower())
        return out


# ── widget ────────────────────────────────────────────────────────────────

_PLACEHOLDER_LABEL = 'Loading…'


class TreeBrowser(Tree[TreeEntry]):
    """Textual ``Tree`` wired to a :class:`TreeAdapter`.

    Lazy expansion: each container node gets a placeholder child, replaced
    on first expand with a live fetch.  Non-container nodes render as
    leaves.

    Emits :class:`TreeBrowser.EntrySelected` when the user hits Enter on a
    node; the handler on the parent widget receives the :class:`TreeEntry`
    (not just the id).  Use ``on_tree_browser_entry_selected`` on the
    parent ``App`` or ``Screen`` to react.
    """

    class EntrySelected(Message):
        """Posted when the user selects (Enter) a tree node."""
        def __init__(self, entry: TreeEntry, node: TreeNode) -> None:
            super().__init__()
            self.entry = entry
            self.node = node

    def __init__(self, adapter: TreeAdapter, *,
                 lazy: bool = True,
                 **kwargs) -> None:
        # Label of the root node comes from the adapter.
        root_entry = adapter.root()
        super().__init__(root_entry.label, data=root_entry, **kwargs)
        self._adapter = adapter
        self._lazy = lazy
        self.show_root = True

    def on_mount(self) -> None:
        self.root.expand()
        if self._lazy and self.root.data and self.root.data.is_container:
            self.root.add_leaf(_PLACEHOLDER_LABEL, data=None)
        elif not self._lazy:
            self._populate(self.root)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        entry = node.data
        if entry is None or not entry.is_container:
            return
        children = list(node.children)
        if len(children) == 1 and children[0].data is None:
            # Placeholder — replace with real fetch.
            children[0].remove()
            self._populate(node)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        entry = event.node.data
        if entry is None:
            return
        self.post_message(self.EntrySelected(entry, event.node))

    def _populate(self, node: TreeNode) -> None:
        entry = node.data
        if entry is None:
            return
        got = list(self._adapter.children(entry))
        if not got:
            node.add_leaf('(empty)', data=None)
            return
        for child in got:
            if child.is_container:
                sub = node.add(child.label, data=child)
                if self._lazy:
                    sub.add_leaf(_PLACEHOLDER_LABEL, data=None)
                else:
                    self._populate(sub)
            else:
                node.add_leaf(child.label, data=child)
