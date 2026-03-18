This repo contains **3 independent products**:

[![gppu](https://github.com/akarelin/gppu/actions/workflows/gppu.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/gppu.yml) [![stable](https://img.shields.io/github/v/release/akarelin/gppu?filter=gppu/v*&exclude_prerelease&label=stable&color=blue)](https://github.com/akarelin/gppu/releases?q=gppu) Core Python utility library<br>
[![Statusline](https://github.com/akarelin/gppu/actions/workflows/statusline.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/statusline.yml) [![stable](https://img.shields.io/github/v/release/akarelin/gppu?filter=statusline/v*&exclude_prerelease&label=stable&color=blue)](https://github.com/akarelin/gppu/releases?q=statusline) Claude Code 2-line status line tool (Linux, macOS, Windows)<br>
[![W11](https://github.com/akarelin/gppu/actions/workflows/w11.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/w11.yml) [![stable](https://img.shields.io/github/v/release/akarelin/gppu?filter=w11/v*&exclude_prerelease&label=stable&color=blue)](https://github.com/akarelin/gppu/releases?q=w11) [**w11**](w11/README.md) Windows 11 utilities & diagnostics (Windows x64)

# GPPU - General Purpose Python Utilities

A utility library for configuration management, logging, data manipulation, type safety, database access, caching, TUI framework, and browser automation.
_All the things_

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
| [`gppu.ad`](AD.md) | `Logger`/`init_logger`, mixins (`mixin_Logger`, `mixin_Config`), `_Base` foundation class, home automation types (`y2list`, `y2path`, `y2topic`, `y2slug`, `y2eid`), `DC` pseudo-dataclass |
| [`gppu.data`](DATA.md) | `Cache` unified caching (JSON/pickle/sqlite/diskcache/DB backends), database base classes: `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy) |
| [`gppu.tui`](TUI.md) | `TUIApp`, `TUILauncher`, `ConfigEditorApp`, `ui_select`, `ui_select_rows` — Textual-based TUI framework with web mode (`--serve`), CLI fallback, app embedding. Requires `tui` extra |
| [`gppu.chrome`](CHROME.md) | `prepare_driver`, `switch_to_mobile`, `switch_to_desktop` — Selenium Chrome driver setup with profile management, crash recovery, mobile/desktop emulation |

### Env - Configuration Management

`Env` is the standard way to load and access configuration in CLI tools and applications.

```python
from gppu import Env
from pathlib import Path

# Initialize: resolves config file path per OS (Linux, WSL, macOS, Windows)
Env(name='myapp', app_path=Path('CRAP/file_indexer'))

# Load YAML config (supports !include directives)
Env.load()

# Typed access via path ("/" separator)
db_host = Env.glob('database/host', default='localhost')
port = Env.glob_int('database/port', default=5432)
tags = Env.glob_list('metadata/tags')
options = Env.glob_dict('database/options')

# Raw config dict
Env.data  # {'database': {'host': 'localhost', ...}}

# Dump config to YAML for debugging
Env.dump()
```

Config file resolution: looks for `<name>.yaml` then `config.yaml` in the app path. Base paths are OS-aware via `PathBuilder` (e.g. `/home/alex` on Linux, `D:\Dev` on Windows).

YAML `!include` support:
```yaml
# main.yaml
app:
  name: MyApp
  database: !include database.yaml
  services: !include services.yaml
```

### Logging

Log functions produce colored terminal output. Color names from `TColor` can be passed inline to colorize arguments.

```python
from gppu import Info, Warn, Error, Debug, Dump

Info('WBLUE', 'server', 'NONE', 'started on port', 'BG', '8080')
Warn('WYELLOW', 'config', 'NONE', 'key missing, using default')
Error('WRED', 'database', 'NONE', 'connection refused')
Debug('GRAY4', 'trace', 'NONE', 'processing item')  # controlled by TRACE_RULES

# Dump object to YAML file for inspection
Dump('debug_state.yml', data)
```

### pfy

```python
from gppu import pfy

pfy(complex_object)  # returns pretty-printed string via pprint
```

### Type Safety and Coercion

```python
from gppu import safe_int, safe_float, safe_list, safe_timedelta

safe_int('42')              # 42
safe_int(None)              # 0 (default)
safe_int('bad', default=-1) # -1

safe_float('23.5°c')        # 23.5 (strips °c, % suffixes)
safe_float(None)            # NaN

safe_list('single')         # ['single']
safe_list(['a', 'b'])       # ['a', 'b']
safe_list({'x': 1, 'y': 2}) # ['x', 'y'] (dict keys)

safe_timedelta('2026-03-14T10:00:00')  # seconds since that datetime
```

### YAML and JSON I/O

```python
from gppu import dict_from_yml, dict_to_yml, dict_from_json, dict_to_json, dict_sanitize

# YAML with !include support
config = dict_from_yml('config.yaml')
dict_to_yml('output.yaml', data)  # indented lists, utf-8, error file on failure

# JSON
data = dict_from_json('data.json')
dict_to_json('out.json', data, indent=2)

# Sanitize complex objects for serialization
# Handles UserDict, UserList, y2list, sets, tuples, nested dicts
# Drops internal keys (api, adapi, AD, context, hide_attributes)
# Puts name/seid/path keys first
clean = dict_sanitize(data)
```

### Dictionary Utilities

```python
from gppu import deepget, deepget_int, deepget_list, deepget_dict
from gppu import deepdict, dict_all_paths, dict_element_append, dict_sort_keylen

# Auto-vivifying nested defaultdict
d = deepdict()
d['a']['b']['c'] = 1

# List all paths in a nested dict
dict_all_paths(config)  # ['database', 'database/host', 'database/port', ...]

# Coerce dict value to list and append
d = {'tags': 'first'}
dict_element_append(d, 'tags', 'second')           # {'tags': ['first', 'second']}
dict_element_append(d, 'tags', 'first', unique=True) # no-op, already present

# Sort dict keys by length (longest first by default)
dict_sort_keylen(d, reverse=True)
```

### Template Population

```python
from gppu import dict_template_populate, template_populate

# $var substitution using string.Template
template = {'greeting': 'Hello $name', 'items': ['$a', '$b']}
result = dict_template_populate(template, {'name': 'Alice', 'a': '1', 'b': '2'})
# {'greeting': 'Hello Alice', 'items': ['1', '2']}

# Special values:
# - 'DEL' removes the key from result
# - '[1, 2, 3]' string is parsed into a list
# - dict keys can reference sibling keys via 'data' sub-dict
# - Functions and excludes are preserved as-is

# Works on any object (returns string for non-dict input)
template_populate('Hello $name', {'name': 'World'})  # 'Hello World'
```

### Time Utilities

```python
from gppu import now_str, now_ts, pretty_timedelta, prepend_datestamp, append_timestamp

now_str()                      # "20260314.153042"
now_ts()                       # 1710423042.123 (Unix timestamp)
pretty_timedelta(earlier_ts)   # "2d 5h 30m 10s"

# File path helpers
prepend_datestamp('report.csv')         # Path("260314 report.csv")
append_timestamp('report.csv')         # Path("report 260314-1530.csv")
prepend_datestamp('report.csv', '_')    # Path("260314_report.csv")
```

### Cache (gppu.data)

Unified caching with multiple backends. Standalone — does not require `Env`.

```python
from gppu.data import Cache

# SQLite backend (default, no extra deps)
cache = Cache('/tmp/my_cache', ttl=3600, backend='sqlite')
cache.set('key', {'data': [1, 2, 3]})
val = cache.get('key')  # returns None if expired

# Decorator for function memoization
@cache
def expensive(x):
    return x ** 2

# Other backends: 'json', 'pickle', 'diskcache', 'db' (SQLAlchemy URL)
# Env-var bypass: set skip_env='SKIP_CACHE' to disable caching via env var
```

### Other Utilities

```python
from gppu import detect_os, slugify, pfy, sync
from gppu.gppu import OSType

# OS detection
detect_os()  # OSType.WSL, OSType.LINUX, OSType.W11, OSType.MACOS, OSType.OTHER

# Slugify any object
slugify('Hello World!')  # 'hello_world_'

# Async-to-sync decorator
@sync
async def fetch_data(): ...
# Can be called from sync code; creates event loop if needed,
# or returns a Task if loop is already running
```

## TColor Reference

Hex values computed from ANSI codes in `gppu/gppu.py` (xterm-256color palette).

<img src="docs/tcolor-reference.svg" alt="TColor reference" width="640">


## LLM Development Guide

Best practices for LLM agents working with `gppu`.

### The LLM Development Workflow: Config First

The entire development process begins with the configuration file. This is a strict, non-negotiable rule.

1.  **Define the Configuration**: The User and the LLM collaborate to define the complete structure of the application's configuration in a `.yaml` file. The LLM can propose a first draft, but the **User must review, edit, and approve the final structure.** This file is the single source of truth.

2.  **Configuration is Everything**: The `.yaml` file must contain all information the application needs to run: paths, credentials, API keys, settings, flags, etc.

3.  **Begin Development**: Only after the configuration structure is finalized can the LLM begin writing the application code.

4.  **Zero-Parameter Execution**: All command-line scripts and utilities developed **must** run without any parameters (e.g., `python3 my_app.py`). The application reads everything it needs from the configuration file loaded by `gppu`.

This config-first approach ensures that the application logic is cleanly separated from its environment and settings, making it portable, predictable, and easy to manage.

### LLM Interaction Rules

-   **Consult on Missing Features:** If you determine that a required feature for environment management, logging, or configuration is not available in the `gppu` library, you **must** stop and ask the user for guidance. Do not attempt to implement a workaround.
-   **Consult on Configuration Changes:** If you believe a new key or section needs to be added to a configuration file to complete a task, you **must** stop and ask the user to approve the change. Do not modify configuration files without explicit permission.

### Core Principle: Initialization

All `gppu`-powered applications start by initializing the `Env` object. This is the single entry point for loading the configuration and setting up the environment.

```python
from gppu import Env
from pathlib import Path

# Initialize Env once at the start of your application.
# Env uses class-level state (singleton) — the instance is not stored.
Env(name='app-name', app_path=Path('CRAP/app_root_directory'))
Env.load()
```

-   `name`: A unique identifier for your application (e.g., `file-indexer`).
-   `app_path`: A **relative** path appended to the OS-specific base directory (`D:\Dev` on Windows, `/home/alex` on Linux). For example, `Path('CRAP/file_indexer')` resolves to `D:\Dev\CRAP\file_indexer` on Windows.

### Configuration: The Two-Tier System

Configuration is split into two levels: a central, shared repository for secrets, and application-specific files that import from it.

**1. Core Configuration (`RAN/Keys`)**

-   The `RAN/Keys` directory is the central, secure repository for all sensitive and shared configuration, such as database credentials, API keys, and other secrets.
-   These files are considered the ultimate source of truth for credentials.

**2. Application Configuration**

-   Each application has its own `config.yaml` file.
-   This file should be lean and focus only on settings specific to that application.
-   It **must** import all necessary core configurations from `RAN/Keys` using the `!include` directive.

**Example Application `config.yaml`:**

```yaml
# Import shared database credentials from the central repository
db: !include D:\Dev\RAN\Keys\postgres\file_indexer.yaml

# Application-specific settings
imessage_workflow:
  mode: 'full'
  max_age_days: 365
```

### Two Core Usage Patterns

**Pattern 1: Direct Calls**

This pattern is straightforward and suitable for scripts. After initializing `Env`, you use `gppu` functions directly.

```python
from gppu import Env, Info, Error, glob, glob_int
from pathlib import Path

# 1. Initialize Env
Env(name='my-app', app_path=Path('CRAP/my_app'))
Env.load()

# 2. Use gppu functions directly
Info('INFO', 'Application started', 'WGREEN', 'OK', 'DIM', '(config loaded)')

# Access configuration
db_connection = glob('db/connection_string')

if not db_connection:
    Error('WRED', 'FATAL', 'DIM', 'Database connection string is missing!', 'BRIGHT', '(check config.yaml)')
```

**Pattern 2: Class-Based (using `_Base`)**

This pattern is for object-oriented applications. Inheriting from `_Base` automatically provides logging and configuration capabilities.

```python
from gppu import _Base, Env
from pathlib import Path

class DataProcessor(_Base):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._config_from_key('data_processor') # Loads the 'data_processor' section

        # Access config and validate
        self._host = self.my('host')
        if not self._host:
            self.Error('WRED', 'Host is missing for this processor.', data=self._my)

    def process(self):
        self.Info('INFO', 'Processing data for host', 'BRIGHT', self._host)

# --- Application Entry Point ---
Env(name='my-app', app_path=Path('CRAP/my_app'))
Env.load()

processor = DataProcessor()
processor.process()
```

**Colored Logging**

Logging messages **must** be structured for clarity using color codes. Pass strings representing colors and the content to be colored as separate arguments.

```python
# Good: Structured, colored, and informative
self.Info('INFO', 'Indexing location', 'BRIGHT', location_id, 'DIM', f'({location_path})')
self.Warn('WYELLOW', 'Permission denied', 'DIM', 'accessing', 'BRIGHT', root_path, 'WRED', f'({e})')
self.Error('WRED', 'Error processing file', 'BRIGHT', file_path, 'WRED', f'({e})')
```

### Strict Anti-Patterns (What to Avoid)

-   **NEVER use fallback defaults.** A missing value is a configuration error that must be fixed in the `.yaml` file.
    -   **Wrong:** `setting = self.my('some/setting', default='default_value')`
    -   **Right:** `setting = self.my('some/setting')` followed by a validation check.

-   **NEVER hardcode example or placeholder values.** Configuration files and code must not contain placeholders like `user@hostname`, `/path/to/downloads`, or `/your/path`.

-   **NEVER parse config files directly.** The `Env` object is the only way to load configuration.
    -   **Wrong:** `my_config = dict_from_yml('config.yaml')`

-   **NEVER use `ConfigLoader`.** This is a deprecated class.

-   **NEVER use command-line arguments for configuration.** All settings belong in `.yaml` files.

-   **NEVER build paths manually.** `gppu` handles OS-specific path resolution automatically. Manual path logic is a critical error.
    -   **Wrong:** `if os_type == OSType.W11: ... else: ...`

### YAML Configuration Rules

-   **No Placeholders:** Your `config.yaml` must be clean of any example or placeholder text.
-   **Use Includes for Modularity:** Import shared configs from `RAN/Keys`.
-   **OS-Specific Paths:** `PathBuilder` handles OS-specific base path resolution automatically via `app_path`. You do not need to define OS-specific roots in your config.

## License

Extracted from RAN project for reuse across Alex Karelin's automation and data processing tools.
