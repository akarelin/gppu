---
fileClass: Document
created: 2026-09-11
updated: 2026-09-12
generated: { by: Codex/GPT-6, at: '2026-09-12' }
---

# Configuration from MQTT

`Env.from_mqtt()` loads compiled YAML or JSON mappings from MQTT and disconnects. Apps that already maintain an MQTT connection can opt into later updates with `mqtt_config()` on their existing `MqttApp` or `mixin_Mqtt` transport. Both use `gppu[mqtt]`. `Env` reports which paths changed; the consuming application decides what to do.

Alex requested MQTT configuration and configuration-specific change handling on 2026-09-11. He clarified that console apps need no reloading, systems may restart to apply changes, and most apps do not maintain an MQTT connection.

| Application need | Loading | Connection lifetime |
| --- | --- | --- |
| Console app or app that restarts to apply configuration | `Env.from_mqtt(source)` | Disconnects after startup configuration arrives |
| App that needs later updates and already maintains MQTT | `app.mqtt_config(topics)` | Uses the app's existing transport |
| App that needs no later updates | No configuration subscription | No background connection for configuration |

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

These are example topic names and a local example broker, not built-in defaults. Connection uses the existing MQTT fields: `hostname`, `port`, `username`, `password`, and `identifier`. Live configuration subscriptions use the app's connection and identifier.

Each topic supplies the complete mapping for its `Env` path. For example, `config/dc` containing `{"scene":"pc"}` replaces the `dc` subtree, including removal of keys omitted from the new mapping. Other subtrees remain unchanged. An empty destination path replaces the whole configuration. Destination paths cannot overlap, because delivery order must not decide which configuration wins.

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

The call returns and disconnects after every declared topic has supplied a mapping. Console apps and applications that restart to apply configuration use this startup load. No background MQTT connection remains.

## Updates through an existing app connection

Only apps that need later updates register configuration topics. Add the registration to the app's existing `subscribe()` method, alongside its normal subscriptions:

```python
from gppu import Env

async def subscribe(self):
  await self.mqtt_config(Env.glob_dict('config_mqtt/topics'))
```

`mqtt_config()` registers subscriptions and returns; it does not start a connection or wait for retained delivery. It also works on an already-connected app. Reconnection replays the subscriptions through the same transport. An app that needs the values before constructing its objects uses startup loading first. Only the app's normal connection receives subsequent updates.

Register a handler for the configuration the app can apply, and unregister it when that consumer stops:

```python
from gppu import Env, Info

def config_changed(paths):
  Info('Configuration changed:', sorted(paths))
  # The application selects its action using these paths and the updated Env.

unsubscribe = Env.on_change(config_changed, path='dc')
# At consumer shutdown: unsubscribe()
```

Save the topic mapping before loading a full-root configuration if the replacement omits the bootstrap section. The app owns connection shutdown. Windows callers use an asyncio SelectorEventLoop, as required by aiomqtt; gppu does not change a process-wide event-loop policy.

Callbacks receive a `frozenset` of changed slash paths after `Env` is updated. Additions, replacements, and deletions are reported. A whole removed subtree also notifies listeners for its descendants. Identical retained replays cause no callback. `Env.changed_paths` exposes the most recent comparison, and `Env.glob_dict('')` reads the whole current configuration.

Callbacks are synchronous and registrations survive reloads until the returned unsubscribe function is called. An application can schedule asynchronous work through its own lifecycle. The loader does not restart services or reinitialize objects that previously copied configuration. Ordinary YAML reloads through `Env.from_env()` and explicit subtree replacements through `Env.update_config(mapping, path)` use the same notifications. No file watcher is installed.

Malformed payloads and non-mapping payloads fail visibly. Configuration callback errors propagate through the app's task lifecycle; they are not reduced to device-callback warnings. Startup loading waits for missing topics; there is no local-config fallback or built-in deadline for the first configuration message. Applications needing a startup deadline can wrap the awaited load with `asyncio.timeout()` using their own declared limit.

Transport references: [aiomqtt subscriptions](https://aiomqtt.bo3hm.com/subscribing-to-a-topic) and [Windows event-loop requirements](https://aiomqtt.bo3hm.com/#note-for-windows-users).
