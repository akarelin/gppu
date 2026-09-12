---
fileClass: Document
created: 2026-09-11
updated: 2026-09-11
generated: { by: Codex/GPT-6, at: '2026-09-11' }
---

# Configuration from MQTT

`Env.from_mqtt()` loads compiled YAML or JSON mappings from MQTT. It uses gppu's existing MQTT transport and reconnection, available with `gppu[mqtt]`. `Env` reports which paths changed; the consuming application decides what to do.

Alex requested MQTT configuration, configuration-specific change handling, and startup-only loading for systems that apply configuration by restarting on 2026-09-11.

Load the local bootstrap through `Env.from_env()`. Pass a configuration mapping with `connection` and `topics` to `Env.from_mqtt()`. The surrounding bootstrap section name is the application's choice; this example calls it `config_mqtt`.

```yaml
config_mqtt:
  connection:
    hostname: localhost
    port: 1883
  topics:
    config/dc: dc
    config/ov: ov
```

These are example topic names and a local example broker, not built-in defaults. Connection uses the existing MQTT fields: `hostname`, `port`, `username`, `password`, and `identifier`. A watcher running beside another MQTT client must have a distinct identifier, or leave it to the MQTT library to generate one.

Each topic supplies the complete mapping for its `Env` path. For example, `config/dc` containing `{"scene":"pc"}` replaces the `dc` subtree, including removal of keys omitted from the new mapping. Other subtrees remain unchanged. An empty destination path replaces the whole configuration. Source paths cannot overlap, because delivery order must not decide which configuration wins.

Publish the compiled payload with retain enabled so it is available to new consumers. Subscriptions use QoS 1. Topics must be exact names, because startup loading waits for every declared topic. MQTT payloads contain resolved YAML/JSON mappings; source-file includes and Jinja compilation belong to the compiler before publication.

## Load at startup

```python
from pathlib import Path
from gppu import Env

async def load_config():
  Env.from_env(name='consumer', app_path=Path(__file__).parent)
  source = Env.glob_dict('config_mqtt')
  await Env.from_mqtt(source)
  return Env.glob_dict('')
```

The call returns and disconnects after every declared topic has supplied a mapping. It does not watch later messages. This is sufficient for an application that restarts to apply new configuration.

## Observe changes

```python
from gppu import Env, Info

def config_changed(paths):
  Info('Configuration changed:', sorted(paths))
  # The application selects its action using these paths and the updated Env.

async def watch_config(source):
  unsubscribe = Env.on_change(config_changed, path='dc')
  try:
    await Env.from_mqtt(source, watch=True)
  finally:
    unsubscribe()
```

Save `source` before loading a full-root MQTT configuration. Run the watcher in the application's existing asyncio task group when other work must continue alongside it. Cancelling the watcher closes its connection. Windows callers use an asyncio SelectorEventLoop, as required by aiomqtt; gppu does not change a process-wide event-loop policy.

Callbacks receive a `frozenset` of changed slash paths after `Env` is updated. Additions, replacements, and deletions are reported. A whole removed subtree also notifies listeners for its descendants. Identical retained replays cause no callback. `Env.changed_paths` exposes the most recent comparison, and `Env.glob_dict('')` reads the whole current configuration.

Callbacks are synchronous and registrations survive reloads until the returned unsubscribe function is called. An application can schedule asynchronous work through its own lifecycle. The loader does not restart services or reinitialize objects that previously copied configuration. Ordinary YAML reloads through `Env.from_env()` and explicit subtree replacements through `Env.update_config(mapping, path)` use the same notifications. No file watcher is installed.

Malformed payloads and non-mapping payloads fail visibly. Missing topics wait for publication; there is no local-config fallback or built-in deadline for the first configuration message. Applications needing a startup deadline can wrap the awaited load with `asyncio.timeout()` using their own declared limit.

Transport references: [aiomqtt subscriptions](https://aiomqtt.bo3hm.com/subscribing-to-a-topic) and [Windows event-loop requirements](https://aiomqtt.bo3hm.com/#note-for-windows-users).
