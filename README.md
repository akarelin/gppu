# GPPU - General Purpose Python Utilities

[![CI](https://github.com/akarelin/gppu/actions/workflows/ci.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/ci.yml)

A utility library for configuration management, logging, data manipulation, type safety, database access, and browser automation. Used across Y2 (home automation), CRAP (data pipelines), and RAN (infrastructure).

## Installation

```bash
# From GitHub
pip install "gppu @ git+ssh://git@github.com/akarelin/gppu.git@latest"

# With optional extras
pip install "gppu[pg] @ git+ssh://git@github.com/akarelin/gppu.git@latest"
pip install "gppu[all] @ git+ssh://git@github.com/akarelin/gppu.git@latest"

# Local development
pip install -e ".[all,test]"
```

**Optional extras**: `pg` (psycopg2), `sql` (SQLAlchemy), `chrome` (Selenium), `all`, `test` (pytest).

Requires Python >= 3.11. Core dependency: PyYAML.

## Modules

| Module | Purpose |
|--------|---------|
| `gppu` (core) | `Env` config loader, type coercion, dict utilities, YAML/JSON I/O, colored logging, time helpers, OS detection, async helpers, template population |
| [`gppu.ad`](AD.md) | `Logger`/`init_logger`, mixins (`mixin_Logger`, `mixin_Config`), `_Base` foundation class, advanced types (`y2list`, `y2path`, `y2topic`, `y2slug`, `y2eid`), `DC` pseudo-dataclass |
| `gppu.data` | Database base classes: `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy) with lazy connections, context managers, auto-commit/rollback |
| `gppu.chrome` | Selenium Chrome driver setup with profile management, process lifecycle, crash recovery, stale lock cleanup, mobile/desktop emulation |

## Public API

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

# Env also gets bound logging methods after init
Env.Info('status', 'loaded config')
Env.Error('db', 'connection failed')
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

For `Logger`, `init_logger`, mixin classes, and `_Base` see [AD.md](AD.md).

### TColor Reference

| Name | Style | | Name | Style |
|------|-------|-|------|-------|
| `NONE` | Reset | | `DIM` | Dim gray |
| `BRIGHT` | Bright cyan | | `BW` | Bright white |
| `DW` | Dark white | | `INFO` | Bright blue |
| **Background** | | | | |
| `WHITE` | Black on white | | `YELLOW` | Black on yellow |
| `RED` | Black on red | | `BLUE` | Black on blue |
| `GREEN` | Black on green | | | |
| `WRED` | White on red | | `WBLUE` | White on blue |
| `WGREEN` | White on green | | `WGRAY` | Black on light gray |
| `WPINK` | Black on pink | | `WPURPLE` | White on purple |
| `WYELLOW` | White on yellow | | | |
| **Text colors** | | | | |
| `BR` | Bright red | | `DR` | Dark red |
| `BG` | Bright green | | `DG` | Dark green |
| `BY` | Bright yellow | | `DY` | Dark yellow |
| `BC` | Bright cyan | | `DC` | Dark cyan |
| `BM` | Bright magenta | | `DM` | Dark magenta |
| `DB` | Dark blue | | | |
| `BP` / `PURPLE` | Bright purple | | `DP` | Dark purple |
| `BO` / `ORANGE` | Bright orange | | `DO` | Dark orange |
| `PINK` | Bright pink | | `DPINK` | Dark pink |
| `BGOLD` | Bright gold | | `DGOLD` | Dark gold |
| **Grays** | | | | |
| `GRAY0` | Darkest | | `GRAY1` | Dark |
| `GRAY2` | Medium | | `GRAY3` | Light |
| `GRAY4` | Lightest | | | |

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

# Path-based nested access ("/" separator)
deepget('database/host', config, default='localhost')
deepget_int('database/port', config, default=5432)
deepget_list('tags', config, default=[])
deepget_dict('options', config, default={})

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

### Advanced Types (gppu.ad)

See [AD.md](AD.md) for full documentation of `y2list`, `y2path`, `y2topic`, `y2slug`, `y2eid`, `DC`, `Logger`, `init_logger`, mixins, and `_Base`.

### Database Access (gppu.data)

Both classes inherit from `_Base` (logger + config). Connection string is resolved from `Env.glob('db')` or `self.my('db')`.

```python
from gppu.data import _PGBase, _SQABase

# PostgreSQL (psycopg2) - lazy connection, dict cursors by default
class MyDB(_PGBase):
    pass

with MyDB(config_key='postgres') as db:
    with db.cursor() as cur:
        cur.execute('SELECT * FROM users')
        rows = cur.fetchall()  # list of RealDictRow
    with db.cursor(dict_cursor=False) as cur:
        cur.execute('SELECT count(*) FROM users')

# SQLAlchemy ORM - lazy engine, session context manager
class MyORM(_SQABase):
    pass

with MyORM(config_key='database') as db:
    with db.session() as sess:
        users = sess.query(User).all()
```

### Chrome Automation (gppu.chrome)

Profile-aware Chrome driver with process lifecycle management.

```python
from gppu.chrome import prepare_driver, switch_to_mobile, switch_to_desktop

# Prepares driver: kills existing Chrome on same profile, removes stale locks,
# clears crash recovery flags, configures download dir
driver = prepare_driver(
    download_directory='~/Downloads',
    user_data_dir='~/.config/chrome-automation',  # default
    profile_directory='Default',                   # optional
    interactive=True,                              # prompt before killing Chrome
)

driver.get('https://example.com')

# CDP-based device emulation
switch_to_mobile(driver)   # iPhone X (375x812, 3x scale)
switch_to_desktop(driver)  # clears emulation

driver.quit()
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

## Branches

- **master** (v2.52.x): Production. Used by: Y2 dev, RAN, CRAP
- **3.0** (v3.0.0.x): Semi-abandoned refactor (Pydantic/Rich). Used by: Y3
- **LTS**: Original v2.18.3 backup

## License

Extracted from RAN project for reuse across Alex Karelin's automation and data processing tools.
