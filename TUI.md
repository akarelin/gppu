# gppu.tui - TUI Framework

`gppu.tui` is a Textual-based framework for building app launchers, config editors, and interactive selectors. Requires the `tui` extra (`pip install gppu[tui]`).

```python
from gppu.tui import (
    TUIApp, TUILauncher, AppScreen,
    ConfigEditorApp,
    Selector, DetailedSelector, ui_select, ui_select_rows,
    launcher_main, load_app_registry,
)
```

## TUIApp

Base class combining Textual's `App` with gppu's `mixin_Config`. All TUI apps inherit from this.

```python
from gppu.tui import TUIApp

class MyApp(TUIApp):
    TITLE = 'My App'

    def compose(self):
        yield Static('Hello')

    def cli(self):
        """CLI fallback when no terminal is available."""
        print('Running in CLI mode')

# Unified entry point — TUI if available, CLI fallback otherwise
MyApp.main()
```

### Key features

- **`done(result)`** — finish the app. Works in both standalone mode (`exit()`) and embedded mode (when pushed as a screen inside a `TUILauncher`, calls `dismiss()`)
- **`cli()`** — override for non-interactive fallback. Called automatically by `main()` when no TTY or Textual is unavailable
- **`main()`** — class method entry point. Detects environment and runs TUI or CLI

## TUILauncher

Superapp launcher that presents a menu of sub-apps defined via YAML manifests. Sub-apps can run as subprocesses (with full terminal handoff), inline background tasks (with log capture), or embedded TUI screens.

### Minimal example

```python
from gppu import Env
from gppu.tui import TUILauncher, launcher_main, load_app_registry

APP_DIR = Path(__file__).parent

class MyLauncher(TUILauncher):
    TITLE = 'My Tools'
    MENU_TITLE = 'Available Tools'

def main():
    Env(name='mytools', app_path=APP_DIR)
    Env.load()
    apps = load_app_registry(APP_DIR)
    launcher_main(apps, MyLauncher, APP_DIR, 'My Tools — launcher')
```

### Real-world example (w11)

```python
# w11/app.py — the entire launcher is 15 lines
from gppu import Env
from gppu.tui import TUILauncher, launcher_main, load_app_registry
from w11 import resolve_app_dir

APP_DIR = resolve_app_dir()

class W11App(TUILauncher):
    TITLE = 'w11'
    MENU_TITLE = 'Windows 11 Tools'

def main():
    Env(name='w11', app_path=APP_DIR)
    Env.load()
    apps = load_app_registry(APP_DIR)
    launcher_main(apps, W11App, APP_DIR, 'w11 — Windows 11 Superapp')
```

### App manifests

Each sub-app is declared in a YAML config referenced by the main config's `apps` key:

```yaml
# mytools.yaml (main config)
apps:
  events: w11-events.yaml
  onedrive: w11-onedrive.yaml
```

```yaml
# w11-events.yaml (sub-app config)
manifest:
  name: Event Monitor
  icon: "\U0001F4CB"
  description: Windows event log viewer
  script: w11-events.py
  modes:
    live:
      name: Live Monitor
      args: [--live]
      inline: true          # run in background with log capture
    report:
      name: Generate Report
      args: [--report]
    custom:
      name: Custom Query
      ask_for:               # prompt user for parameters before launch
        - name: source
          options: [System, Application, Security]
        - name: hours
          default: 24

# App-specific config below the manifest
default_hours: 24
sources: [System, Application]
```

### Manifest keys

| Key | Description |
|-----|-------------|
| `name` | Display name in the menu |
| `icon` | Unicode icon shown next to the name |
| `description` | Short description shown dimmed |
| `script` | Python script path (relative to app dir) |
| `cwd` | Working directory override (default: script's parent) |
| `module` / `class` | Import a `TUIApp` subclass and push it as an embedded screen instead of launching a subprocess |
| `modes` | Dict of named launch modes (see below) |

### Mode keys

| Key | Description |
|-----|-------------|
| `name` | Display name for the mode |
| `args` | CLI arguments list passed to the script |
| `inline` | If `true`, run in background with spinner and log capture instead of suspending the TUI |
| `ask_for` | List of parameter prompts shown before launch. Each can have `name`, `default`, and `options` |
| `module` / `class` | Override app-level module/class for this mode |

### Execution modes

1. **Subprocess (default)** — TUI exits, sub-app gets full terminal, TUI resumes when sub-app finishes
2. **Inline** (`inline: true`) — runs in background with a spinner row showing live status. User can keep navigating. Click the row or press `o` to view captured output
3. **Embedded TUI** (`module` + `class`) — imports a `TUIApp` subclass and pushes it as a screen. The app runs inside the launcher with `done()` returning to the menu
4. **Background task** (`run_task()`) — programmatic API for running a function in a worker thread with log capture

### Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Launch selected app/mode |
| `Escape` | Back (modes → apps → quit) |
| `q` | Quit |
| `i` | Show Env config info |
| `o` | Toggle output panel |
| `d` | Toggle dark/light mode |
| `Ctrl+P` | Command palette |

## Web mode

Serve any launcher as a web app using `textual-serve`. Requires the `serve` extra (`pip install gppu[serve]`).

```bash
# From CLI
python myapp.py --serve [--port 8566] [--host localhost]
```

The `--serve` flag starts an HTTP server that renders the TUI in a browser via WebSocket. Same keybindings and functionality as the terminal version.

## CLI fallback

When no interactive terminal is available (no TTY, piped stdin, SSH without allocation), the launcher automatically falls back to a numbered menu:

```
  1. 📋  Event Monitor — Windows event log viewer
  2. 💾  OneDrive — OneDrive diagnostics
  q. Quit

Select:
```

Individual `TUIApp` subclasses can also provide their own CLI fallback by overriding the `cli()` method.

## ConfigEditorApp

TUI editor for YAML config files with `!include` tree traversal.

```python
from gppu.tui import ConfigEditorApp

# Standalone
ConfigEditorApp.main(root_config=Path('config.yaml'))

# Or embed in a launcher via manifest:
# module: gppu.tui.config_editor
# class: ConfigEditorApp
```

### Features

- **File tree** — discovers all YAML files via recursive `!include` traversal from the root config
- **Live preview** — shows file content with line numbers, `!include` targets, and validation status
- **Inline editing** — TextArea with YAML syntax highlighting and line numbers
- **Validation** — tolerates `!include` tags while checking YAML syntax. Validate individual files or all at once
- **CLI fallback** — numbered file list with external editor ($VISUAL/$EDITOR) when no TUI is available

### Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Edit selected file (or save if already editing) |
| `Escape` | Save and close editor / quit |
| `v` | Validate all files |
| `r` | Refresh file tree |
| `q` | Quit |

## Selector widgets

Quick-launch picker apps for scripts that need a one-shot TUI selection.

### ui_select

Pick one item from a list:

```python
from gppu.tui import ui_select

choice = ui_select(['alpha', 'beta', 'gamma'])
# Returns the selected string, or exits on Escape
```

### ui_select_rows

Pick rows from a table with checkbox selection and detail expand:

```python
from gppu.tui import ui_select_rows

rows = [
    {'name': 'Alice', 'age': 30, 'notes': 'Manager'},
    {'name': 'Bob', 'age': 25, 'notes': 'Developer'},
]
selected = ui_select_rows(
    rows,
    summary_keys=['name', 'age'],       # columns shown in table
    expanded_keys=['name', 'age', 'notes'],  # fields shown on detail expand
)
# Returns list of selected row dicts, or None on Escape
```

| Key | Action |
|-----|--------|
| `Space` | Toggle row selection |
| `Enter` | Confirm selection |
| `e` | Expand row details |
| `Escape` | Cancel |

## Widgets

Reusable components available for custom TUI apps:

| Widget | Description |
|--------|-------------|
| `StatusHeader` | Drop-in `Header` replacement with right-aligned subtitle |
| `SpinnerIndicator` | Animated spinner with start/stop/reset |
| `ProcessRow` | Background process row with spinner and log toggle |
| `InfoScreen` | Modal screen showing key/value sections |
| `AppItem` | Menu list item for an app entry |
| `ModeItem` | Menu list item for a mode entry |
| `AppScreen` | Wraps a `TUIApp` as a pushable screen within a launcher |
