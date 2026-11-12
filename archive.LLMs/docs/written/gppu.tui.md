<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/tui/__init__.py ccdf5338b1dbf35fa4212105cb71c58eb804a5de -->
## gppu.tui

`gppu.tui` is gppu's toolkit for terminal user interfaces. It provides a launcher that starts a set of TUI apps from one place, along with the reusable widgets those apps are built from: list selectors, a YAML config editor, progress indicators, a concurrent worker display, icons, a heatmap, modal dialogs, cached data loaders, a tree browser, and a task matrix.

The launcher is the centre of the module. `TUIApp` and `AppScreen` are the base classes an app builds on. `TUILauncher` keeps the registry of sub-apps and starts them. The registry is read from manifests through `read_manifest`, `load_registry`, and `load_app_registry`. Sidecar manifests follow the same route through `load_sidecar_registry`, `read_sidecar`, and `run_sidecar`. `launch_app` starts one entry, and `launcher_main` is the entry point that runs the launcher from the command line.

The other parts are standalone widgets that an app uses directly:

- **Selectors:** `ui_select` and `ui_select_rows` show a list picker. `Selector` and `DetailedSelector` are the widgets behind them, and the detailed one shows its pane through `DetailScreen`.
- **Config editing:** `ConfigEditorApp` edits YAML configuration.
- **Progress:** `TickProgress` shows a dim indicator per item, and `MarkerProgress` shows a coloured glyph for each item's classification. `Marker` names those classifications, and `legend_rich` and `legend_ansi` draw a legend for them.
- **Workers:** `WorkerPool` holds `WorkerRow` entries, each with a `WorkerState`, stacked with an aggregate footer.
- **Icons:** `Glyph`, `STATE_GLYPHS`, and `SPINNERS` define the state glyphs and spinner frame sets. `glyph_rich`, `glyph_ansi`, and `spinner_frames` render them.
- **Viz:** `Heatmap` and `render_heatmap_lines` draw an activity grid.
- **Modals:** `ConfirmScreen` and `InputScreen` ask for a confirmation or a line of input.
- **Data:** `LoaderMixin`, `CachedFetcher`, `PaginatedFetcher`, and `CacheRefreshMixin` load and cache data for a screen.
- **Trees:** `TreeBrowser` browses a tree of `TreeEntry` nodes supplied by a `TreeAdapter`. `FilesystemAdapter` and `GDriveAdapter` are the provided adapters. `TreeTable` and `TreeTableColumn` show tabular data.
- **Tasks:** `TaskMatrix` shows a grid of tasks.

Import everything an app needs from the package:

```python
from gppu.tui import TUIApp, TUILauncher, AppScreen, launch_app, launcher_main
from gppu.tui import ui_select, ConfigEditorApp, WorkerPool
```

An app subclasses `TUIApp` or `AppScreen`, its manifest is read into the registry, and `launcher_main` starts the launcher that runs it. Each class and function is described in the reference below.
