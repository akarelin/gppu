# GPPU — General Purpose Python Utilities

<h3><code>v3</code> — <em>All the things</em></h3>

> YAML-driven configuration with `!include` and `!secret`, colored structured logging, secret management (Azure Key Vault / env-vars), type coercion, deep dict access, YAML/JSON I/O, template population, time helpers, OS detection, async-to-sync, multi-backend caching, PostgreSQL and SQLAlchemy base classes, Textual TUI framework with superapp launchers, nested apps, config editors, web UI via `--serve`, and CLI fallback, Selenium Chrome automation, and home automation types.

[![CI](https://github.com/akarelin/gppu/actions/workflows/gppu.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/gppu.yml) [![release](https://img.shields.io/github/v/release/akarelin/gppu?filter=gppu/v*&label=&color=blue&style=flat-square)](https://github.com/akarelin/gppu/releases?q=gppu)


<table>
<tr>
<td width="140"><strong><a href="statusline/status_line.py">Statusline</a></strong></td>
<td><a href="https://github.com/akarelin/gppu/actions/workflows/statusline.yml"><img src="https://img.shields.io/github/actions/workflow/status/akarelin/gppu/statusline.yml?label=&style=flat-square" alt="CI"></a> <a href="https://github.com/akarelin/gppu/releases?q=statusline"><img src="https://img.shields.io/github/v/release/akarelin/gppu?filter=statusline/v*&label=&color=blue&style=flat-square" alt="release"></a></td>
<td>Claude Code 2-line status line (Linux, macOS, Windows)</td>
</tr>
<tr>
<td><strong><a href="w11/README.md">W11</a></strong></td>
<td><a href="https://github.com/akarelin/gppu/actions/workflows/w11.yml"><img src="https://img.shields.io/github/actions/workflow/status/akarelin/gppu/w11.yml?label=&style=flat-square" alt="CI"></a> <a href="https://github.com/akarelin/gppu/releases?q=w11"><img src="https://img.shields.io/github/v/release/akarelin/gppu?filter=w11/v*&label=&color=blue&style=flat-square" alt="release"></a></td>
<td>Windows 11 utilities &amp; diagnostics</td>
</tr>
<tr>
<td><strong><a href="rust/README.md">GPRU</a></strong></td>
<td><a href="https://github.com/akarelin/gppu/actions/workflows/rust-branch-build.yml"><img src="https://img.shields.io/github/actions/workflow/status/akarelin/gppu/rust-branch-build.yml?label=&style=flat-square" alt="CI"></a> <img src="https://img.shields.io/badge/status-in%20progress-yellow?style=flat-square" alt="in progress"></td>
<td>Rust port of <code>gppu</code> (in progress)</td>
</tr>
</table>

---
# Modules

| Module | Purpose |
|--------|---------|
| `gppu` (core)<br> | **Environment**: `Env` config loader with `!include`, typed path access (`glob`, `glob_int`, `glob_list`, `glob_dict`). <br>**Logger**: colored `Info`/`Warn`/`Error`/`Debug`/`Dump`. <br>**Vault**: `Vault.get`/`create`/`update`/`list` with Azure Key Vault and `SECRET_*` env-var backends; `!secret` YAML tag.<br>Plus: type coercion, dict utilities, YAML/JSON I/O, time helpers, OS detection + `full_path` path resolution (env vars, `~`, WSL drive mapping), async helpers, template population |
| `gppu.ymro` | YMRO lifecycle: multi-inheritance-aware init→load→start steppers (`YInit`/`YLoad`/`YStart`/`mixin_Stepper`).<br>`Tracer` flight recorder: JSONL trace of object snapshots, triggers, callbacks, and periodic state (AppDaemon hooks via `Tracer.install`); `_tracer` before/after/instead method decorators |
| [`gppu.data`](DATA.md) | `Cache` unified caching (JSON/pickle/sqlite/diskcache/DB backends), <br>database base classes: `_PGBase` (psycopg2) and `_SQABase` (SQLAlchemy),<br>`_PersistentDC` persisted pseudo-dataclasses with `Persistence` multi-backend storage (json/pickle/sqlite/postgres) |
| [`gppu.iot`](IOT.md) | y2 types: `y2list`, `y2path`, `y2topic`, `y2slug`, `y2eid` (token-list strings for topics/slugs/entity ids).<br>MQTT plumbing for the any2mqtt services: `mqtt_connstring`, `MqttMixin` (reconnecting aiomqtt client with callback dispatch, MQTT5 expiry/user-properties), `Transformer` (config-driven scalar transform stage).<br>Control mixins: `_IORuntime` (thread-hosted asyncio loop, per-key gating), `_HTTPControl` (aiohttp), `_SerialControl` (telnetlib3), `_SerialHTTPControl`. Third-party deps via `mqtt`/`iot` extras |
| [`gppu.tui`](TUI.md) | `TUIApp`, `TUILauncher`, `ConfigEditorApp`, `ui_select`, `ui_select_rows`<br> Textual-based TUI framework with web mode (`--serve`), CLI fallback, app embedding. Requires `tui` extra |
| [`gppu.chrome`](CHROME.md) | `prepare_driver`, `switch_to_mobile`, `switch_to_desktop`<br>Selenium Chrome driver setup with profile management, crash recovery, mobile/desktop emulation |

## Environment

```python
from gppu import Env
from pathlib import Path

# Initialize: resolves config file, loads YAML (with !include and !secret support)
Env.from_env(name='myapp', app_path=Path(__file__).parent)

# Typed access via "/" path
db_host = Env.glob('database/host', default='localhost')
port    = Env.glob_int('database/port', default=5432)
tags    = Env.glob_list('metadata/tags')
options = Env.glob_dict('database/options')
```

Config file resolution: looks for `<name>.yaml` then `config.yaml` in the app path. Relative `app_path` values are resolved by walking up from the calling script's directory until a matching subpath is found.

YAML `!include` support:
```yaml
app:
  name: MyApp
  database: !include database.yaml
```

## Logger

```python
from gppu import Info, Warn, Error, Debug, Dump

Info('WBLUE', 'server', 'NONE', 'started on port', 'BG', '8080')
Warn('WYELLOW', 'config', 'NONE', 'key missing, using default')
Error('WRED', 'database', 'NONE', 'connection refused')
Debug('GRAY4', 'trace', 'NONE', 'processing item')

Dump('debug_state.yml', data)
```

## Vault

Static facade over a pluggable provider chain. Provider auto-detected on first use: `AZURE_KEYVAULT_NAME` → Azure Key Vault, else `SECRET_*` env-vars. `SECRET_<NAME>` env vars always win over the persistent provider.

```python
from gppu import Vault

token   = Vault.get('anthropic-api-key')           # checks SECRET_ANTHROPIC_API_KEY first
Vault.create('slack-bot-token', 'xoxb-...')         # raises if it already exists
Vault.create('slack-bot-token', 'xoxb-...', designation='T01')  # collision → slack-bot-token-t01
Vault.update('openai-api-key', 'sk-...', create=True)
names = Vault.list()                                # env-var union with provider listing
```

In YAML: `password: !secret db-pass` resolves at load time via `Vault.get`. Requires the `vault` (or `vault-azure`) extra.

## How Apps Work

Every app follows the same pattern: a YAML config file is the single source of truth, and `Env.from_env()` loads it at startup. The app reads all its settings from `Env.glob()`.

### 1. Create a config — `myapp.yaml` next to your script:

```yaml
logs:
  - Application
  - System
level: Warning
days: 30
error_rules: !include error_rules.yaml
```

### 2. Initialize and read config:

```python
from gppu import Env, Info, glob, glob_int, glob_list
from pathlib import Path

Env.from_env(name='myapp', app_path=Path(__file__).parent)

logs  = glob_list('logs')
level = glob('level', default='Warning')
days  = glob_int('days', default=10)

Info('WBLUE', 'myapp', 'NONE', 'loaded', 'BG', str(len(logs)), 'NONE', 'logs')
```

### 3. For TUI apps — subclass `TUIApp` and use `Env` the same way:

```python
from gppu import Env
from gppu.tui import TUIApp

class MyApp(TUIApp):
    TITLE = 'My App'
    def compose(self):
        ...

Env.from_env(name='myapp', app_path=Path(__file__).parent)
MyApp.main()  # TUI if terminal available, CLI fallback otherwise
```

### 4. For superapp launchers — a launcher config lists sub-apps, each with its own YAML:

```yaml
# launcher.yaml
apps:
  events: events.yaml
  onedrive: onedrive.yaml
```

Each sub-app YAML has a `manifest:` section (name, icon, script, modes) plus app-specific config below it. The launcher loads all manifests and presents a menu.

```python
from gppu import Env
from gppu.tui import TUILauncher, launcher_main, load_app_registry

APP_DIR = Path(__file__).parent

class MyLauncher(TUILauncher):
    TITLE = 'My Tools'

Env.from_env(name='launcher', app_path=APP_DIR)
apps = load_app_registry(APP_DIR)
launcher_main(apps, MyLauncher, APP_DIR, 'My Tools')
```

See [w11/app.py](w11/app.py) for a real example.

# Other Products

[Statusline](statusline/status_line.py) — Claude Code status line tool

[W11](w11/README.md) — Windows 11 utilities


# Appendix
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

**Optional extras**: `pg` (psycopg2), `sql` (SQLAlchemy), `cache` (diskcache), `mqtt` (aiomqtt), `iot` (aiomqtt + aiohttp + telnetlib3), `chrome` (Selenium), `tui` (Textual), `serve` (textual-serve), `statusline` (Jinja2), `vault-azure`, `vault` (= `vault-azure`), `all`, `test` (pytest), `test-tui` (pytest + pytest-asyncio + textual).

Requires Python >= 3.11. Core dependency: PyYAML.

## TColor Reference

Hex values computed from ANSI codes in `gppu/gppu.py` (xterm-256color palette).

<img src="docs/tcolor-reference.svg" alt="TColor reference" width="640">


## License

Extracted from RAN project for reuse across Alex Karelin's automation and data processing tools.
