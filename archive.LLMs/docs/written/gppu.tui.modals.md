<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/modals.py 64627d83c71bc170203c258cf701264ca992c76d -->
## Modal dialogs

`gppu.tui.modals` provides two modal dialogs for TUI apps: a yes-or-no confirmation and a single-line text prompt. Each covers the screen while it is open, then passes the user's answer back to the app.

## The two screens

`ConfirmScreen` shows a message with Y and N choices. Y dismisses it with `True`. N and Esc dismiss it with `False`.

`InputScreen` shows a label above a text field, pre-filled with an optional default. Submitting the field dismisses the screen with the entered text, stripped of surrounding whitespace. Esc dismisses it with an empty string.

Both are `ModalScreen` subclasses. The app opens one with `push_screen`, passing a callback as the second argument. The screen only collects the answer. The callback decides what the app does with it.

`InputScreen` takes a `require_value` flag. By default, an empty submit dismisses with an empty string, the same value as a cancel, so the callback cannot tell them apart. With `require_value=True`, an empty submit leaves the field focused and does not dismiss. Only Esc cancels, so an empty string in the callback always means the user cancelled.

## Usage

A program opens a screen with `push_screen` and handles the answer in the callback:

```python
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
```
