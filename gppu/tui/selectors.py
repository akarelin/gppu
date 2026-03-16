"""Reusable Textual selector widgets.

Quick-launch picker apps for use in scripts that need a one-shot TUI selection
then return to regular CLI flow.

Usage::

    from gppu.tui import ui_select, ui_select_rows

    choice = ui_select(['alpha', 'beta', 'gamma'])

    rows = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]
    selected = ui_select_rows(rows, summary_keys=['name', 'age'])
"""

from __future__ import annotations

import sys

from textual import events
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Label, ListItem, ListView, Static


# ── Selector ─────────────────────────────────────────────────────────────────

class Selector(App):
    """Pick one item from a list.  Returns the label string, or ``None`` on Escape."""

    CSS = """
    App {
        align: center middle;
    }
    #selector-window {
        width: auto;
        height: auto;
        border: round;
        padding: 1;
    }
    """

    def __init__(self, options: list[str], **kw) -> None:
        super().__init__(**kw)
        self.options = options

    def compose(self) -> ComposeResult:
        yield ListView(
            *[ListItem(Label(opt)) for opt in self.options],
            id='selector-window',
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.exit(event.item.query_exactly_one(Label).renderable)

    async def on_key(self, event: events.Key) -> None:
        if event.key == 'escape':
            self.exit(None)


# ── DetailedSelector ─────────────────────────────────────────────────────────

class DetailScreen(Screen):
    """Modal screen showing expanded row details."""

    CSS = """
    #modal {
        width: 60%;
        height: 60%;
        border: round;
        padding: 1;
        background: $boost;
    }
    """

    def __init__(self, details_text: str) -> None:
        super().__init__()
        self.details_text = details_text

    def compose(self) -> ComposeResult:
        yield Static(self.details_text, id='modal')

    async def on_key(self, event: events.Key) -> None:
        if event.key in ('escape', 'enter'):
            await self.app.pop_screen()


class DetailedSelector(App):
    """Pick rows from a table with checkbox selection and detail expand.

    Returns a list of selected row dicts on Enter, or ``None`` on Escape.
    Press Space to toggle a row, ``e`` to expand details.
    """

    CSS = """
    App {
        align: center middle;
    }
    #data-table {
        width: auto;
        height: auto;
        border: round;
        padding: 1;
    }
    """

    def __init__(
        self,
        rows: list[dict],
        summary_keys: list[str],
        expanded_keys: list[str] | None = None,
        never_keys: list[str] | None = None,
        **kw,
    ) -> None:
        super().__init__(**kw)
        self.rows = rows
        self.summary_keys = summary_keys
        self.expanded_keys = expanded_keys or list(summary_keys)
        self.never_keys = set(never_keys or [])
        self.selected: dict[int, bool] = {}

    def compose(self) -> ComposeResult:
        table = DataTable(id='data-table')
        table.add_column('Select', width=8)
        for key in self.summary_keys:
            table.add_column(key)
        for i, row in enumerate(self.rows):
            summary = [str(row.get(key, '')) for key in self.summary_keys]
            table.add_row('[ ]', *summary, key=i)
            self.selected[i] = False
        yield table

    async def on_key(self, event: events.Key) -> None:
        table = self.query_one('#data-table', DataTable)
        if event.key == 'escape':
            self.exit(None)
        elif event.key == 'space':
            if table.cursor_row is not None:
                row_index = table.get_row_key(table.cursor_row)
                self.selected[row_index] = not self.selected[row_index]
                new_box = '[X]' if self.selected[row_index] else '[ ]'
                table.update_cell(table.cursor_row, 0, new_box)
        elif event.key == 'enter':
            selected_rows = [
                self.rows[i] for i, sel in self.selected.items() if sel
            ]
            self.exit(selected_rows)
        elif event.key == 'e':
            if table.cursor_row is not None:
                row_index = table.get_row_key(table.cursor_row)
                row = self.rows[row_index]
                details = [
                    f'{key}: {row[key]}'
                    for key in self.expanded_keys
                    if key in row and key not in self.never_keys
                ]
                await self.push_screen(DetailScreen('\n'.join(details)))


# ── Convenience functions ────────────────────────────────────────────────────

def ui_select(options: list[str], *, exit_on_none: bool = True) -> str | None:
    """Show a list picker.  Returns the chosen string or ``None``.

    If *exit_on_none* is True (default), ``sys.exit(0)`` on Escape.
    """
    result = Selector(options).run()
    if result is None and exit_on_none:
        sys.exit(0)
    return result


def ui_select_rows(
    rows: list[dict],
    summary_keys: list[str],
    expanded_keys: list[str] | None = None,
    never_keys: list[str] | None = None,
) -> list[dict] | None:
    """Show a table picker with checkbox selection.  Returns selected rows."""
    return DetailedSelector(
        rows, summary_keys, expanded_keys, never_keys,
    ).run()
