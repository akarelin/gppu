<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/selectors.py 7f163babfe7a073b72f3becee024af0760083b97 -->
The module provides Textual pickers for scripts that need one choice from the user and then return to ordinary command-line work. Each picker runs as a short-lived TUI and hands its result back when it closes.

## How the pieces fit

`Selector` is a Textual app that shows a list of strings. It returns the label of the item the user picks, or `None` if the user presses Escape. `ui_select` runs a `Selector` and returns that result. Unless `exit_on_none` is false, `ui_select` ends the process with exit code 0 on Escape instead of returning `None`.

`DetailedSelector` is a Textual app that shows rows as a table with a checkbox column. Space toggles the checkbox of the row under the cursor. Enter returns the checked rows, and Escape returns `None`. `initial_selected` pre-checks rows by index. Pressing `e` opens `DetailScreen`, a modal screen listing `key: value` lines for the row's expanded keys, skipping any key in `never_keys`. When `expanded_keys` is not given, it defaults to `summary_keys`. Enter or Escape closes `DetailScreen`. `ui_select_rows` runs a `DetailedSelector` and returns its result.

## Usage

`ui_select` and `ui_select_rows` are the convenience functions, and most scripts only need those two.

```python
from gppu.tui import ui_select, ui_select_rows

choice = ui_select(['alpha', 'beta', 'gamma'])

rows = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]
selected = ui_select_rows(rows, summary_keys=['name', 'age'])
```

The first call returns the chosen string. Because `exit_on_none` defaults to true, pressing Escape there ends the script. The second call returns the checked rows, or `None` when the user presses Escape.
