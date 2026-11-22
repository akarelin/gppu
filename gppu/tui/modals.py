"""The confirmation dialog: "Are you sure?".

Push it with ``app.push_screen(ConfirmScreen(...), callback)``; the callback receives the answer as a ``bool``.

    from gppu.tui import ConfirmScreen

    def on_delete(self):
        def _on_answer(ok: bool) -> None:
            if ok:
                self._do_delete()
        self.push_screen(ConfirmScreen('Delete this record?'), _on_answer)
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No confirmation modal.  Returns ``True`` on Y, ``False`` on N/Esc."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-box {
        width: 50;
        height: auto;
        max-height: 12;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #confirm-message {
        margin-bottom: 1;
    }
    #confirm-buttons {
        height: 3;
        align: center middle;
    }
    """

    BINDINGS = [
        Binding('y',      'confirm', 'Yes'),
        Binding('n',      'cancel',  'No'),
        Binding('escape', 'cancel',  'Cancel'),
    ]

    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id='confirm-box'):
            yield Static(self._message, id='confirm-message')
            with Center(id='confirm-buttons'):
                yield Static('[bold green]Y[/bold green]es  /  [bold red]N[/bold red]o')

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
