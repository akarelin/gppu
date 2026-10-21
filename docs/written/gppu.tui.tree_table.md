<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/tree_table.py a44bd9c4afc476c4c2b0c86b63280b2fa00877ee -->
`gppu.tui.tree_table` provides an expandable table for hierarchical data in a Textual app. Each row is one entry from a tree adapter, shown in a tree column followed by metadata columns. The widget handles the hierarchy and table interaction, while the adapter loads and renders the data. The DataTable presentation and refresh pattern are adapted from `GindaChen/nsys-ai`'s `TreeTable` (MIT License, Copyright 2025 GindaChen).

`TreeTableColumn` describes one column after the tree column. Its `key` names an entry in the entry's `meta` dictionary, `label` is the header, and the optional `width` fixes the column width. A row with no value for the key shows an empty cell.

`TreeTable` is the widget. It takes a `TreeAdapter` from `gppu.tui.tree`, which supplies the root entry, the children of a container, and the label and metadata of each `TreeEntry`. Loading is lazy: a container's children are requested only when it is expanded, and loaded children are kept so a refresh can reuse them. The table shows the root and the children of each expanded node, indented by depth. A collapsed container is marked ▶ and an expanded one ▼. The first column is titled `tree_label`, which defaults to `Name`.

The keys work as follows. Left or `h` collapses an expanded container, or moves the cursor to the parent when the row is already collapsed or is a leaf. Right or `l` expands a container. Space toggles it. Enter toggles a container and posts `EntrySelected` for any entry. Moving the cursor posts `EntryHighlighted`. Both messages carry the `entry`.

Code that changes the tree from outside uses these methods. `reset()` rebuilds the whole hierarchy from the adapter root. `refresh_entry()` reloads one entry's branch, and can replace the entry itself, while every other row, expansion and selection stays in place. `expand()`, `collapse()` and `select()` take an entry id, and `select()` moves the cursor only to a row that is currently visible. The `selected_entry` property returns the entry under the cursor, and `expanded_ids` returns the ids of all expanded entries.

## Use

Create the widget with an adapter and yield it from `compose`. Handle the `EntrySelected` and `EntryHighlighted` messages in the app or a parent widget to react to the user's choices.

```python
from textual.app import App, ComposeResult

from gppu.tui.tree import TreeAdapter
from gppu.tui.tree_table import TreeTable, TreeTableColumn


class Browser(App):
    def __init__(self, adapter: TreeAdapter) -> None:
        super().__init__()
        self.adapter = adapter

    def compose(self) -> ComposeResult:
        yield TreeTable(
            self.adapter,
            columns=(TreeTableColumn(key='size', label='Size', width=12),),  # key must match a meta key the adapter sets
            tree_label='Name',
        )
```
