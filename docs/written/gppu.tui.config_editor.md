<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/config_editor.py 4332704c9727ac83e1a5845a46eb4f1782aaabc2 -->
The `gppu.tui.config_editor` module edits YAML configuration files and checks that they parse. It finds the files to edit by following `!include` lines from a root YAML config, so a configuration split across several files can be edited from one place.

## How the parts fit together

File discovery starts from the root config. `find_direct_includes` reads one file and returns the paths its `!include` lines name, resolved against that file's folder. `walk_includes` follows those paths recursively and skips files it has already visited, so include cycles end. `collect_yaml_targets` builds the editable list from the walked files, every `.yaml` file under any extra directory, and any extra files. `extend_unique` removes duplicates while keeping the order.

Validation is separate from discovery. `validate_yaml` parses a file with `LoaderWithInclude`, a YAML loader that accepts `!include` tags. Before parsing, `_normalize_bare_includes` rewrites bare `!include path` lines into list items. The function returns a success flag and an error message.

`pick_editor` chooses the terminal editor from `VISUAL`, then `EDITOR`, then the first of `nano`, `vim` or `vi` that is installed.

`ConfigEditorApp` is a TUI built on `TUIApp`. Its left pane is a file tree. Its right pane previews the highlighted file with its validity, its first 100 lines and its includes. Enter opens the file in a text area, Esc saves it and validates it, `v` validates every file, `r` refreshes the tree, and `q` quits. A file that does not exist yet appears as missing and is created when edited. File names are shown relative to `project_root`, which defaults to the folder of the root config.

The `cli()` method of the app calls `_cli_editor`, the fallback for a terminal without the TUI. It prints a numbered list of files, asks for a number, offers to create a missing file, opens the file in the editor, and reports whether the result validates.

## Using the module

A program can start the editor with the root config alone:

```python
from pathlib import Path
from gppu.tui.config_editor import ConfigEditorApp

ConfigEditorApp.main(root_config=Path('config.yaml'))
```

The constructor also accepts `extra_dirs`, `extra_files` and `project_root` to add files to the list and change how paths are shown.
