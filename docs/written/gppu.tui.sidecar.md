<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/sidecar.py abfb672878c02026cfb4fb5a6abb6c4f18f428a8 -->
Sidecar manifests expose an existing script as a launcher item without editing the script. A utility named `{name}.{ext}` (`.py`, `.ps1`, `.cmd` or `.sh`) is registered by a sidecar named `{name}.{ext}.md` beside it. The sidecar's YAML frontmatter is the launcher manifest. The script path comes from the sidecar's filename, and the prose below the frontmatter is ignored.

## How the parts work together

`read_sidecar` turns one sidecar into a manifest. It checks that the utility exists, parses the frontmatter, and rejects unknown keys, including unknown keys inside a mode. It fills in the defaults: the name is the utility's stem, the script and working directory are the utility's own path and folder, and `.cmd` and `.ps1` utilities default to the `W11` platform.

`load_sidecar_registry` collects the sidecars in one or more directories. It warns about and skips a missing directory, and it raises an error on a duplicate item key. A `key` in the frontmatter overrides the default key, which is the utility's stem. The result is ordered by `nav` path, then display name.

Each entry under `modes` gives one way to run the utility. A mode passes values on the command line with `args` or `ask_for`, or writes constants into the source with `inject`. A mode marked `inline` cannot inject.

Injection never writes the original file. `inject_source` writes a temporary copy beside the source, replaces each named top-level assignment in it, and fails if a name has no assignment. Injection is defined for `.py`, `.ps1`, `.sh` and `.cmd` sources.

`run_sidecar` runs one item. An item with a `url` opens in the browser and runs nothing. Otherwise it injects any constants, chooses the interpreter with `sidecar_command`, runs the utility with UTF-8 environment settings, and deletes the injected copy afterward. `sidecar_command` raises an error when the interpreter it needs (`pwsh`, `bash`, or `COMSPEC`) is missing.

`sidecar_main` is the entry point for a container of utilities. It accepts an item name, a `--list` flag, and trailing arguments for the item. It refuses an item whose platform does not match the current OS. With no item name, it creates the TUI class you pass as `app_class`, runs it, and runs the item the user selects, repeating until the user exits. Without a terminal, it requires an item name.

## Usage

```python
from pathlib import Path

from gppu.tui.sidecar import load_sidecar_registry, sidecar_main

UTILITY_DIR = Path('utilities')
apps = load_sidecar_registry(UTILITY_DIR)
raise SystemExit(sidecar_main(apps, MyLauncher, UTILITY_DIR, 'Utilities'))
```

`MyLauncher` stands for your TUI app class. It is constructed with the registry and the directory, and its `run()` returns the chosen item with its arguments and injected values, or nothing to exit.
