This repo contains **3 independent products**:

[![gppu](https://github.com/akarelin/gppu/actions/workflows/gppu.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/gppu.yml) [![stable](https://img.shields.io/github/v/release/akarelin/gppu?filter=gppu/v*&exclude_prerelease&label=stable&color=blue)](https://github.com/akarelin/gppu/releases?q=gppu) Core Python utility library<br>
[![Statusline](https://github.com/akarelin/gppu/actions/workflows/statusline.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/statusline.yml) [![stable](https://img.shields.io/github/v/release/akarelin/gppu?filter=statusline/v*&exclude_prerelease&label=stable&color=blue)](https://github.com/akarelin/gppu/releases?q=statusline) Claude Code 2-line status line tool (Linux, macOS, Windows)<br>
[![W11](https://github.com/akarelin/gppu/actions/workflows/w11.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/w11.yml) [![stable](https://img.shields.io/github/v/release/akarelin/gppu?filter=w11/v*&exclude_prerelease&label=stable&color=blue)](https://github.com/akarelin/gppu/releases?q=w11) [**w11**](w11/README.md) Windows 11 utilities & diagnostics (Windows x64)

# GPPU - General Purpose Python Utilities

A utility library for configuration management, logging, data manipulation, type safety, database access, caching, TUI framework, and browser automation.
> _All the things_

## Installation

```bash
# From GitHub
pip install "gppu @ git+ssh://git@github.com/akarelin/gppu.git@gppu/latest"

# With optional extras
pip install "gppu[pg] @ git+ssh://git@github.com/akarelin/gppu.git@gppu/latest"
pip install "gppu[all] @ git+ssh://git@github.com/akarelin/gppu.git@gppu/latest"

# Local development
pip install -e ".[all,test]"
```

**Optional extras**: `pg` (psycopg2), `sql` (SQLAlchemy), `cache` (diskcache), `chrome` (Selenium), `tui` (Textual), `serve` (textual-serve), `statusline` (Jinja2), `all`, `test` (pytest).

Requires Python >= 3.11. Core dependency: PyYAML.

## Modules

| Module | Purpose |
|--------|---------|
| `gppu` (core) | **Environment**: `Env` config loader with `!include`, typed path access (`glob`, `glob_int`, `glob_list`, `glob_dict`). **Logger**: colored `Info`/`Warn`/`Error`/`Debug`/`Dump`. Plus: type coercion, dict utilities, YAML/JSON I/O, time helpers, OS detection, async helpers, template population |
| [`gppu.ad`](AD.md) | Mixins (`mixin_Logger`, `mixin_Config`), `_Base` foundation class, home automation types (`y2list`, `y2path`, `y2topic`, `y2slug`, `y2eid`), `DC` pseudo-dataclass |
| [`gppu.data`](DATA.md) | `Cache` unified caching (JSON/pickle/sqlite/diskcache/DB backends), database base classes: `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy) |
| [`gppu.tui`](TUI.md) | `TUIApp`, `TUILauncher`, `ConfigEditorApp`, `ui_select`, `ui_select_rows` — Textual-based TUI framework with web mode (`--serve`), CLI fallback, app embedding. Requires `tui` extra |
| [`gppu.chrome`](CHROME.md) | `prepare_driver`, `switch_to_mobile`, `switch_to_desktop` — Selenium Chrome driver setup with profile management, crash recovery, mobile/desktop emulation |

## TColor Reference

Hex values computed from ANSI codes in `gppu/gppu.py` (xterm-256color palette).

<img src="docs/tcolor-reference.svg" alt="TColor reference" width="640">


## LLM Development Guide

### Config-First Workflow

1.  **Define the Configuration**: User and LLM collaborate on the `.yaml` file. **User must approve the final structure.** This is the single source of truth.
2.  **Configuration is Everything**: Paths, credentials, API keys, settings, flags — all in `.yaml`.
3.  **Begin Development**: Only after the config is finalized.
4.  **Zero-Parameter Execution**: All scripts **must** run without parameters. Everything comes from `Env`.

### Interaction Rules

-   **Consult on Missing Features:** If a required feature is not in `gppu`, **stop and ask** the user. Do not implement workarounds.
-   **Consult on Configuration Changes:** If a new config key is needed, **stop and ask**. Do not modify config files without permission.

### Configuration: Two-Tier System

-   **`RAN/Keys`** — central secure repository for all secrets (DB credentials, API keys). Source of truth.
-   **Application config** — lean, app-specific `.yaml` that imports from `RAN/Keys` via `!include`.

```yaml
db: !include D:\Dev\RAN\Keys\postgres\file_indexer.yaml
imessage_workflow:
  mode: 'full'
  max_age_days: 365
```

### Two Usage Patterns

**Pattern 1: Direct Calls** — for scripts:

```python
from gppu import Env, Info, Error, glob
Env(name='my-app', app_path=Path('CRAP/my_app'))
Env.load()
Info('INFO', 'Started', 'WGREEN', 'OK')
db_connection = glob('db/connection_string')
```

**Pattern 2: Class-Based** — inheriting `_Base` gives logging + config:

```python
from gppu import _Base, Env
class DataProcessor(_Base):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._config_from_key('data_processor')
        self._host = self.my('host')
    def process(self):
        self.Info('INFO', 'Processing', 'BRIGHT', self._host)
```

### Strict Anti-Patterns

-   **NEVER use fallback defaults.** Missing value = config error. Fix the `.yaml`.
-   **NEVER hardcode placeholders** like `user@hostname` or `/path/to/`.
-   **NEVER parse config directly.** Use `Env`, not `dict_from_yml('config.yaml')`.
-   **NEVER use `ConfigLoader`.** Deprecated.
-   **NEVER use CLI arguments for config.** All settings go in `.yaml`.
-   **NEVER build paths manually.** `PathBuilder` handles OS-specific resolution.

## License

Extracted from RAN project for reuse across Alex Karelin's automation and data processing tools.
