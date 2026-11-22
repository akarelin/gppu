"""Tests for gppu.tui.tree and gppu.tui.tree_table: TreeEntry, and TreeTable over an adapter."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from gppu.tui.tree import TreeAdapter, TreeEntry
from gppu.tui.tree_table import TreeTable, TreeTableColumn

# .. ── TreeEntry ────────────────────────────────────────────────────────────

class TestTreeEntry:
    def test_defaults(self):
        e = TreeEntry(id='/a', label='a')
        assert e.is_container is False
        assert e.meta == {}

    def test_meta_is_own_dict(self):
        a = TreeEntry(id='a', label='a')
        b = TreeEntry(id='b', label='b')
        a.meta['x'] = 1
        assert 'x' not in b.meta  # .. no shared default


# .. ── FilesystemAdapter ────────────────────────────────────────────────────

# .. ── GDriveAdapter (stubbed service) ──────────────────────────────────────

# .. ── TreeTable ────────────────────────────────────────────────────────────

class _TableAdapter:
    def __init__(self):
        self.folder = TreeEntry(
            id='folder',
            label='Folder',
            is_container=True,
            meta={'state': 'Not indexed'},
        )

    def root(self):
        return TreeEntry(id='root', label='Locations', is_container=True)

    def children(self, entry):
        if entry.id == 'root':
            return [TreeEntry(id='host', label='alex-pc', is_container=True)]
        if entry.id == 'host':
            return [self.folder]
        return []


class _TableApp(App):
    def __init__(self, adapter):
        super().__init__()
        self.adapter = adapter

    def compose(self) -> ComposeResult:
        yield TreeTable(
            self.adapter,
            columns=(TreeTableColumn('state', 'State', 100),),
            id='tree-table',
        )


def test_tree_table_expands_without_empty_rows_and_preserves_selection():
    async def exercise():
        adapter = _TableAdapter()
        app = _TableApp(adapter)
        async with app.run_test() as pilot:
            tree = app.query_one('#tree-table', TreeTable)
            table = tree.query_one(DataTable)
            assert table.row_count == 2

            table.focus()
            tree.select('host')
            await pilot.press('right')
            await pilot.pause()
            assert table.row_count == 3

            tree.select('folder')
            await pilot.pause()
            assert tree.selected_entry.id == 'folder'

            await pilot.press('right')
            await pilot.pause()
            assert table.row_count == 3
            assert tree.selected_entry.id == 'folder'

            await pilot.press('left')
            assert 'folder' not in tree.expanded_ids
            await pilot.press('right')
            assert 'folder' in tree.expanded_ids

            adapter.folder = TreeEntry(
                id='folder',
                label='Folder',
                is_container=True,
                meta={'state': 'Indexed'},
            )
            tree.refresh_entry('host')
            await pilot.pause()
            assert tree.selected_entry.id == 'folder'
            assert {'root', 'host', 'folder'} <= tree.expanded_ids

    asyncio.run(exercise())
