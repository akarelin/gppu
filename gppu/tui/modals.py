"""Modal dialogs — Confirm and Input.

Two small ``ModalScreen`` subclasses that every TUI app wants at some
point: "Are you sure?" and "Enter a name".  Push via
``app.push_screen(ConfirmScreen(...), callback)`` — the callback receives
the user's answer (``bool`` for Confirm, ``str`` for Input; empty string
on cancel).

Lifted from DA (``A/DA/da/tui.py:398-495``), kept as close to the
original shape as possible so consumers can replace the ad-hoc version
with a one-line import swap.

Example::

    from gppu.tui import ConfirmScreen, InputScreen

    def on_delete(self):
        def _on_answer(ok: bool) -> None:
            if ok:
                self._do_delete()
        self.push_screen(ConfirmScreen('Delete this record?'), _on_answer)

    def on_rename(self, current: str):
        def _on_name(new: str) -> None:
            if new:
                self._rename_to(new)
        self.push_screen(InputScreen('New name:', default=current), _on_name)
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


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


class InputScreen(ModalScreen[str]):
    """Single-line text-input modal.

    Returns the entered text on submit, or an empty string on Esc / cancel.
    Callers distinguishing "empty-submit" from "cancel" should pass
    ``require_value=True`` — the modal then refuses to dismiss on empty
    submit and only cancels via Esc.
    """

    DEFAULT_CSS = """
    InputScreen {
        align: center middle;
    }
    #input-box {
        width: 60;
        height: auto;
        max-height: 10;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #input-label {
        margin-bottom: 1;
    }
    #input-field {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding('escape', 'cancel', 'Cancel'),
    ]

    def __init__(self, label: str, default: str = '',
                 *, require_value: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._default = default
        self._require_value = require_value

    def compose(self) -> ComposeResult:
        with Vertical(id='input-box'):
            yield Static(self._label, id='input-label')
            yield Input(value=self._default, id='input-field')

    def on_mount(self) -> None:
        self.query_one('#input-field', Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'input-field':
            return
        val = event.value.strip()
        if self._require_value and not val:
            # Refuse empty submit — leave focus in input for retry.
            return
        self.dismiss(val)

    def action_cancel(self) -> None:
        self.dismiss('')
