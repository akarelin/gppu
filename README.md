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
| [`gppu.data`](DATA.md) | `Cache` unified caching (JSON/pickle/sqlite/diskcache/DB backends), database base classes: `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy) |
| [`gppu.tui`](TUI.md) | `TUIApp`, `TUILauncher`, `ConfigEditorApp`, `ui_select`, `ui_select_rows` — Textual-based TUI framework with web mode (`--serve`), CLI fallback, app embedding. Requires `tui` extra |
| [`gppu.chrome`](CHROME.md) | `prepare_driver`, `switch_to_mobile`, `switch_to_desktop` — Selenium Chrome driver setup with profile management, crash recovery, mobile/desktop emulation |
| [`gppu.ad`](AD.md) | Home automation types (`y2list`, `y2path`, `y2topic`, `y2slug`, `y2eid`), `DC` pseudo-dataclass |

## Usage

### Environment

```python
from gppu import Env
from pathlib import Path

# Initialize: resolves config file, loads YAML (with !include support)
Env.from_env(name='myapp', app_path=Path('CRAP/file_indexer'))

# Typed access via "/" path
db_host = Env.glob('database/host', default='localhost')
port    = Env.glob_int('database/port', default=5432)
tags    = Env.glob_list('metadata/tags')
options = Env.glob_dict('database/options')
```

Config file resolution: looks for `<name>.yaml` then `config.yaml` in the app path. Base paths are OS-aware (e.g. `/home/alex` on Linux, `D:\Dev` on Windows).

YAML `!include` support:
```yaml
app:
  name: MyApp
  database: !include database.yaml
```

### Logger

```python
from gppu import Info, Warn, Error, Debug, Dump

Info('WBLUE', 'server', 'NONE', 'started on port', 'BG', '8080')
Warn('WYELLOW', 'config', 'NONE', 'key missing, using default')
Error('WRED', 'database', 'NONE', 'connection refused')
Debug('GRAY4', 'trace', 'NONE', 'processing item')

Dump('debug_state.yml', data)
```

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

### Usage Pattern

```python
from gppu import Env, Info, Error, glob

Env.from_env(name='my-app', app_path=Path('CRAP/my_app'))
Info('INFO', 'Started', 'WGREEN', 'OK')
db_connection = glob('db/connection_string')
```

### Strict Anti-Patterns

-   **NEVER use fallback defaults.** Missing value = config error. Fix the `.yaml`.
-   **NEVER hardcode placeholders** like `user@hostname` or `/path/to/`.
-   **NEVER parse config directly.** Use `Env`, not `dict_from_yml('config.yaml')`.
-   **NEVER use CLI arguments for config.** All settings go in `.yaml`.
-   **NEVER build paths manually.** `Env` handles OS-specific path resolution.

## License

Extracted from RAN project for reuse across Alex Karelin's automation and data processing tools.
