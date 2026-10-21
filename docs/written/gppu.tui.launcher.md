<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/launcher.py f7021d3da3edb055e6c8721cf3b349c427ba98b3 -->
The `gppu.tui.launcher` module provides a reusable Textual menu that starts sub-apps described by YAML manifests. A consumer writes a thin wrapper with its own `Env` setup and branding, and the module supplies the menu, the run loop, and process handling.

## How the pieces fit

`TUILauncher` is the menu application. A subclass sets `TITLE` and `MENU_TITLE`, and can set `SECTIONS` to group the start screen under headings. Manifests that declare a `nav` collapse into one row per nav, built by `group_apps`. Selecting an app opens its modes when it has more than one, asks for the parameters a mode declares with `ask_for`, and then either exits the menu so the sub-app runs as a subprocess, runs inline with a background process row and log panel, or imports the `TUIApp` class named in the manifest and pushes it as a screen. `TUILauncher.run_task` runs a function in a worker thread with its own spinner row and log.

`TUIApp` is the base class for a Textual sub-app. It runs standalone through `main()`, or embedded in a launcher through `AppScreen`, and `done(result)` finishes it in either case. When no interactive terminal is available, `main()` calls `cli()` instead.

The loaders build the menu's data. `read_manifest` reads one YAML file and resolves its `script` and `cwd` against the manifest's own directory. `load_app_registry` reads the manifests named under `apps:` in the configuration, and `load_registry` is what a launcher calls: it adds the sidecars found in each directory named under `utilities:`. `launch_app` runs a manifest's script in a new process, or opens its `url` in the browser, and returns the exit code. A manifest's `platform` key restricts an app or mode to named operating systems. Restricted items still appear in the menu, labelled with the platform they need.

`launcher_main` is the entry point. It parses the command line and accepts an app name to launch directly, `--list`, `--serve` with `--port` and `--host` (which need textual-serve), and extra arguments passed to the sub-app. Without a direct launch, it runs the menu in a loop, starting the chosen sub-app each time the menu exits with one. If no TUI is available, it shows a numbered menu instead.

## Usage

The module's own docstring shows the minimal wrapper:

```python
from gppu import Env
from gppu.tui import TUILauncher, launcher_main, load_app_registry

class MyApp(TUILauncher):
    TITLE = 'My Tools'
    MENU_TITLE = 'My Tools'

def main():
    Env.from_env(name='myapp', app_path=APP_DIR)
    apps = load_app_registry(APP_DIR)
    launcher_main(apps, MyApp, APP_DIR, 'My Tools — launcher')
```

Run with `--serve` to serve the same menu as a web app on localhost.
