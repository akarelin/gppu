<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/__init__.py a8f9b48bdca32df5ffa9f36a39795eb8c45ef0ce -->
gppu is the top-level package of General Purpose Python Utilities. It holds shared code for reading configuration, logging, templating, coercing types, handling time and strings, and building apps, including MQTT services and AppDaemon/Y2 apps. Programs import from `gppu` itself. The submodules hold the implementations.

## What it contains

Configuration is the center. `Env` and the `glob` family read configuration by key, and `mixin_Config` gives a class the same access. `dict_from_yml` and `dict_from_json` load structured files, and `dict_to_yml` and `dict_to_json` write them back. Templates go through `jinja_template`, `jinja_document` and `template_populate`, with `JinjaEnvironment`, `JinjaDocument` and `TemplateSet` behind them. `Vault` and its providers load on first use, and importing them gives `dict_from_yml` the `!secret` tag.

Apps share one foundation, `_Base`. `App` runs direct calls, `AsyncApp` runs under asyncio, and `APIApp` adds REST through `mixin_Rest`. Synchronous AppDaemon and Y2 apps use `YStepper` and `mixin_Stepper`. `MqttApp` and `mixin_Mqtt` cover MQTT, which needs the `gppu[mqtt]` extra for aiomqtt. `AppService` is an app that runs all the time and reloads its configuration from MQTT. `mixin_EventLoopBridge`, `SerializedControl`, `HTTPControl` and `JSONHTTPControl` bridge event loops and device control.

Logging is `Debug`, `Info`, `Warn`, `Error` and `Dump`, built on `Logger` and `mixin_Logger`. `TRACE_RULES` is a global configuration value that applies across the package.

Smaller helpers sit beside these. The `deepget` and `deepdict` family navigates nested dictionaries. The `safe_` functions coerce values to int, float, list or timedelta. Time, string, colored-print and human-readable formatting helpers round out the set, along with `OSType` and `detect_os`. The Y2 helpers `y2path`, `y2uri`, `y2topic`, `y2list`, `y2slug` and `y2eid` build and format Y2 identifiers. File-system types `Container`, `DataObject`, `FileSystem`, `Location` and `Provider` come from `gppu.fs`.

## Using it

Import what the program needs from the top level:

```python
from gppu import Info, Vault, dict_from_yml, glob  # configuration, logging, secrets
```

The reference below gives the signature and docstring of each name.
