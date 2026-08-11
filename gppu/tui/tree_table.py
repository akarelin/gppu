"""Expandable, adapter-backed table for hierarchical data.

The DataTable-backed presentation and cursor-preserving refresh pattern are
adapted from ``GindaChen/nsys-ai``'s ``TreeTable`` (MIT License, Copyright
2025 GindaChen).  FileIndexer-specific loading and rendering remain in its
adapter; this widget owns only reusable hierarchy and table interaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from .tree import TreeAdapter, TreeEntry


@dataclass(frozen=True)
class TreeTableColumn:
    """One metadata-backed column shown after the expandable tree column."""

    key: str
    label: str
    width: int | None = None


@dataclass
class _Node:
    entry: TreeEntry
    parent: _Node | None = None
    children: list[_Node] = field(default_factory=list)
    expanded: bool = False
    children_loaded: bool = False

    @property
    def depth(self) -> int:
        depth = 0
        parent = self.parent
        while parent is not None:
            depth += 1
            parent = parent.parent
        return depth


class TreeTable(Widget):
    """Lazy expandable hierarchy rendered in Textual's existing ``DataTable``.

    The adapter contract is the same as :class:`TreeBrowser`.  Container
    children are requested only when expanded.  ``refresh_entry`` replaces one
    loaded branch while preserving expansion, selection, and every other row.
    """

    DEFAULT_CSS = """
    TreeTable { height: 1fr; }
    TreeTable > DataTable { height: 1fr; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding('left,h', 'collapse', 'Collapse', show=False),
        Binding('right,l', 'expand', 'Expand', show=False),
        Binding('space', 'toggle', 'Expand / collapse', show=False),
    ]

    class EntryHighlighted(Message):
        """Posted when the cursor moves to a real adapter entry."""

        def __init__(self, entry: TreeEntry) -> None:
            self.entry = entry
            super().__init__()

    class EntrySelected(Message):
        """Posted when Enter selects a real adapter entry."""

        def __init__(self, entry: TreeEntry) -> None:
            self.entry = entry
            super().__init__()

    def __init__(
        self,
        adapter: TreeAdapter,
        *,
        columns: Sequence[TreeTableColumn] = (),
        tree_label: str = 'Name',
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._adapter = adapter
        self.columns = tuple(columns)
        self.tree_label = tree_label
        self._root = _Node(adapter.root(), expanded=True)
        self._tree_nodes: dict[str, _Node] = {self._root.entry.id: self._root}
        self._visible: list[_Node] = []

    def compose(self) -> ComposeResult:
        yield DataTable(cursor_type='row', zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column(self.tree_label, key='tree')
        for column in self.columns:
            table.add_column(column.label, width=column.width, key=column.key)
        self._ensure_children(self._root)
        self._rebuild()

    @property
    def selected_entry(self) -> TreeEntry | None:
        node = self._selected_node()
        return node.entry if node is not None else None

    @property
    def expanded_ids(self) -> set[str]:
        return {node.entry.id for node in self._tree_nodes.values() if node.expanded}

    def reset(self) -> None:
        """Replace the complete hierarchy from the adapter root."""

        self._root = _Node(self._adapter.root(), expanded=True)
        self._tree_nodes = {self._root.entry.id: self._root}
        self._ensure_children(self._root)
        self._rebuild()

    def refresh_entry(
        self,
        entry_id: str,
        *,
        entry: TreeEntry | None = None,
        reload_children: bool = True,
    ) -> None:
        """Refresh one row/branch without resetting the rest of the tree."""

        node = self._tree_nodes.get(entry_id)
        if node is None:
            return
        if entry is not None:
            node.entry = entry
        if reload_children and node.entry.is_container:
            node.children_loaded = False
            if node.expanded:
                self._ensure_children(node)
        self._rebuild()

    def expand(self, entry_id: str) -> None:
        node = self._tree_nodes.get(entry_id)
        if node is None or not node.entry.is_container:
            return
        node.expanded = True
        self._ensure_children(node)
        self._rebuild(preferred_id=entry_id)

    def collapse(self, entry_id: str) -> None:
        node = self._tree_nodes.get(entry_id)
        if node is None or not node.entry.is_container:
            return
        node.expanded = False
        self._rebuild(preferred_id=entry_id)

    def select(self, entry_id: str) -> None:
        for index, node in enumerate(self._visible):
            if node.entry.id == entry_id:
                self.query_one(DataTable).move_cursor(row=index)
                return

    def _ensure_children(self, node: _Node) -> None:
        if node.children_loaded or not node.entry.is_container:
            return
        self._replace_children(node, self._adapter.children(node.entry))
        node.children_loaded = True

    def _replace_children(self, parent: _Node, entries: Iterable[TreeEntry]) -> None:
        existing = {child.entry.id: child for child in parent.children}
        children: list[_Node] = []
        for entry in entries:
            child = existing.get(entry.id)
            if child is None:
                child = _Node(entry=entry, parent=parent)
            else:
                child.entry = entry
                child.parent = parent
            children.append(child)
        parent.children = children
        self._reindex_nodes()

    def _reindex_nodes(self) -> None:
        nodes: dict[str, _Node] = {}

        def visit(node: _Node) -> None:
            nodes[node.entry.id] = node
            for child in node.children:
                visit(child)

        visit(self._root)
        self._tree_nodes = nodes

    def _visible_nodes(self) -> list[_Node]:
        visible: list[_Node] = []

        def visit(node: _Node) -> None:
            visible.append(node)
            if not node.expanded:
                return
            for child in node.children:
                visit(child)

        visit(self._root)
        return visible

    @staticmethod
    def _tree_cell(node: _Node) -> Text:
        prefix = Text('  ' * node.depth)
        if node.entry.is_container:
            prefix.append('▼ ' if node.expanded else '▶ ', style='cyan')
        else:
            prefix.append('  ')
        label = node.entry.label
        prefix.append_text(label.copy() if isinstance(label, Text) else Text(str(label)))
        return prefix

    def _rebuild(self, *, preferred_id: str | None = None) -> None:
        table = self.query_one(DataTable)
        previous_index = table.cursor_row if self._visible else 0
        selected = self._selected_node()
        selected_id = preferred_id or (selected.entry.id if selected is not None else None)
        self._visible = self._visible_nodes()
        table.clear()
        for node in self._visible:
            values: list[Any] = [self._tree_cell(node)]
            values.extend(node.entry.meta.get(column.key, '') for column in self.columns)
            table.add_row(*values, key=node.entry.id)
        if not self._visible:
            return
        target = next(
            (
                index
                for index, node in enumerate(self._visible)
                if node.entry.id == selected_id
            ),
            min(previous_index, len(self._visible) - 1),
        )
        table.move_cursor(row=target)

    def _selected_node(self) -> _Node | None:
        if not self._visible:
            return None
        row = self.query_one(DataTable).cursor_row
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        node = self._selected_node()
        if node is not None:
            self.post_message(self.EntryHighlighted(node.entry))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        node = self._selected_node()
        if node is None:
            return
        if node.entry.is_container:
            node.expanded = not node.expanded
            if node.expanded:
                self._ensure_children(node)
            self._rebuild(preferred_id=node.entry.id)
        self.post_message(self.EntrySelected(node.entry))

    def action_toggle(self) -> None:
        node = self._selected_node()
        if node is None or not node.entry.is_container:
            return
        node.expanded = not node.expanded
        if node.expanded:
            self._ensure_children(node)
        self._rebuild(preferred_id=node.entry.id)

    def action_expand(self) -> None:
        node = self._selected_node()
        if node is not None:
            self.expand(node.entry.id)

    def action_collapse(self) -> None:
        node = self._selected_node()
        if node is None:
            return
        if node.expanded:
            self.collapse(node.entry.id)
        elif node.parent is not None:
            self.select(node.parent.entry.id)
