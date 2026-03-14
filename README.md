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
| [`gppu.data`](DATA.md) | Database base classes: `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy) with lazy connections, context managers, auto-commit/rollback |
| [`gppu.chrome`](CHROME.md) | Selenium Chrome driver setup with profile management, process lifecycle, crash recovery, stale lock cleanup, mobile/desktop emulation |

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

### Advanced Types (gppu.ad)

See [AD.md](AD.md) for full documentation of `y2list`, `y2path`, `y2topic`, `y2slug`, `y2eid`, `DC`, `Logger`, `init_logger`, mixins, and `_Base`.

### Database Access (gppu.data)

See [DATA.md](DATA.md) for `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy).

### Chrome Automation (gppu.chrome)

See [CHROME.md](CHROME.md) for `prepare_driver`, `switch_to_mobile`, `switch_to_desktop`.

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

Hex values computed from ANSI codes in `gppu/gppu.py`. Palette: xterm-256color (index 0-7 standard, 8-15 bright, 16-231 = 6x6x6 cube, 232-255 grayscale).

<!-- 256-color formula: 16-231 → 16+36r+6g+b, levels=[0,95,135,175,215,255]; 232-255 → 8+(i-232)*10 -->

<table>
<tr><th colspan="4">General</th></tr>
<tr>
  <td><code>NONE</code></td><td>Reset <code>0m</code></td>
  <td><code>DIM</code></td><td><span style="color:#808080">██</span> <code>#808080</code> Dim gray</td>
</tr>
<tr>
  <td><code>BRIGHT</code></td><td><span style="color:#00ffff">██</span> <code>#00ffff</code> Bright cyan</td>
  <td><code>INFO</code></td><td><span style="color:#5555ff">██</span> <code>#5555ff</code> Bright blue</td>
</tr>
<tr>
  <td><code>BW</code></td><td><span style="color:#ffffff">██</span> <code>#ffffff</code> Bright white</td>
  <td><code>DW</code></td><td><span style="color:#c0c0c0">██</span> <code>#c0c0c0</code> Dark white</td>
</tr>
<tr><th colspan="4">Background</th></tr>
<tr>
  <td><code>RED</code></td><td><span style="background:#800000;color:#000000;padding:1px 6px">RED</span></td>
  <td><code>BLUE</code></td><td><span style="background:#000080;color:#000000;padding:1px 6px">BLUE</span></td>
</tr>
<tr>
  <td><code>GREEN</code></td><td><span style="background:#008000;color:#000000;padding:1px 6px">GREEN</span></td>
  <td><code>YELLOW</code></td><td><span style="background:#808000;color:#000000;padding:1px 6px">YELLOW</span></td>
</tr>
<tr>
  <td><code>WHITE</code></td><td><span style="background:#c0c0c0;color:#000000;padding:1px 6px">WHITE</span></td>
  <td></td><td></td>
</tr>
<tr>
  <td><code>WRED</code></td><td><span style="background:#800000;color:#c0c0c0;padding:1px 6px">WRED</span></td>
  <td><code>WBLUE</code></td><td><span style="background:#000080;color:#c0c0c0;padding:1px 6px">WBLUE</span></td>
</tr>
<tr>
  <td><code>WGREEN</code></td><td><span style="background:#008000;color:#c0c0c0;padding:1px 6px">WGREEN</span></td>
  <td><code>WGRAY</code></td><td><span style="background:#c0c0c0;color:#000000;padding:1px 6px">WGRAY</span></td>
</tr>
<tr>
  <td><code>WPINK</code></td><td><span style="background:#800080;color:#000000;padding:1px 6px">WPINK</span></td>
  <td><code>WPURPLE</code></td><td><span style="background:#800080;color:#c0c0c0;padding:1px 6px">WPURPLE</span></td>
</tr>
<tr>
  <td><code>WYELLOW</code></td><td><span style="background:#ffff00;color:#000000;padding:1px 6px">WYELLOW</span></td>
  <td></td><td></td>
</tr>
<tr><th colspan="4">Text colors</th></tr>
<tr>
  <td><code>BR</code></td><td><span style="color:#ff0000">██</span> <code>#ff0000</code> Bright red</td>
  <td><code>DR</code></td><td><span style="color:#800000">██</span> <code>#800000</code> Dark red</td>
</tr>
<tr>
  <td><code>BG</code></td><td><span style="color:#00ff00">██</span> <code>#00ff00</code> Bright green</td>
  <td><code>DG</code></td><td><span style="color:#008000">██</span> <code>#008000</code> Dark green</td>
</tr>
<tr>
  <td><code>BY</code></td><td><span style="color:#ffff00">██</span> <code>#ffff00</code> Bright yellow</td>
  <td><code>DY</code></td><td><span style="color:#808000">██</span> <code>#808000</code> Dark yellow</td>
</tr>
<tr>
  <td><code>BC</code></td><td><span style="color:#008080">██</span> <code>#008080</code> Cyan</td>
  <td><code>DC</code></td><td><span style="color:#00ffff">██</span> <code>#00ffff</code> Bright cyan</td>
</tr>
<tr>
  <td><code>BM</code></td><td><span style="color:#ff00ff">██</span> <code>#ff00ff</code> Bright magenta</td>
  <td><code>DM</code></td><td><span style="color:#800080">██</span> <code>#800080</code> Dark magenta</td>
</tr>
<tr>
  <td><code>DB</code></td><td><span style="color:#000080">██</span> <code>#000080</code> Dark blue</td>
  <td></td><td></td>
</tr>
<tr>
  <td><code>BP</code> / <code>PURPLE</code></td><td><span style="color:#af00ff">██</span> <code>#af00ff</code> Bright purple</td>
  <td><code>DP</code></td><td><span style="color:#870087">██</span> <code>#870087</code> Dark purple</td>
</tr>
<tr>
  <td><code>BO</code> / <code>ORANGE</code></td><td><span style="color:#af5f00">██</span> <code>#af5f00</code> Orange</td>
  <td><code>DO</code></td><td><span style="color:#af5f00">██</span> <code>#af5f00</code> Dark orange</td>
</tr>
<tr>
  <td><code>PINK</code></td><td><span style="color:#ff00d7">██</span> <code>#ff00d7</code> Bright pink</td>
  <td><code>DPINK</code></td><td><span style="color:#af5f87">██</span> <code>#af5f87</code> Dark pink</td>
</tr>
<tr>
  <td><code>BGOLD</code></td><td><span style="color:#ffd700">██</span> <code>#ffd700</code> Bright gold</td>
  <td><code>DGOLD</code></td><td><span style="color:#d7af00">██</span> <code>#d7af00</code> Dark gold</td>
</tr>
<tr><th colspan="4">Grays (232-255 grayscale ramp)</th></tr>
<tr>
  <td><code>GRAY0</code></td><td><span style="color:#3a3a3a">██</span> <code>#3a3a3a</code></td>
  <td><code>GRAY1</code></td><td><span style="color:#444444">██</span> <code>#444444</code></td>
</tr>
<tr>
  <td><code>GRAY2</code></td><td><span style="color:#767676">██</span> <code>#767676</code></td>
  <td><code>GRAY3</code></td><td><span style="color:#949494">██</span> <code>#949494</code></td>
</tr>
<tr>
  <td><code>GRAY4</code></td><td><span style="color:#b2b2b2">██</span> <code>#b2b2b2</code></td>
  <td></td><td></td>
</tr>
</table>

## Branches

- **master** (v2.52.x): Production. Used by: Y2 dev, RAN, CRAP
- **3.0** (v3.0.0.x): Semi-abandoned refactor (Pydantic/Rich). Used by: Y3
- **LTS**: Original v2.18.3 backup

## License

Extracted from RAN project for reuse across Alex Karelin's automation and data processing tools.
