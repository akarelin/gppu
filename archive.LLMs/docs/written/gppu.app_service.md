<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/app_service.py a5e38f3e201bf462f40320e2a4526d96f58a7848 -->
`gppu.app_service` runs an app that stays up and reloads its configuration from MQTT. The app's `config_mqtt/topics` setting maps each retained MQTT topic to the configuration path that the topic's payload replaces.

## How the pieces work together

`AppService` is an `MqttApp`. When it loads, it subscribes to each topic in `config_mqtt/topics` at QoS 1, and it raises any error from subscribing. `Env` must already be initialized with `Env.from_env()`, or loading raises `RuntimeError`. Each message is parsed as YAML if it is a string, and it must be a mapping. The mapping then replaces the subtree of `Env` at the path the topic maps to.

`update_config` does the replacement. It works on a copy of the current configuration and replaces the subtree at the given path. An empty path replaces the whole configuration. It then compares the old and new configuration and stores the changed slash paths in the class attribute `changed_paths`. Added and removed keys count as changes. Dictionaries are compared key by key. Lists are compared as JSON. Scalars count as changed when their type or value differs. If `Env` is already initialized and nothing changed, the reload and the callbacks are skipped. Otherwise `Env` reloads, and each callback whose path overlaps a changed path is called with the changed paths that overlap it. The root path overlaps every change. A callback runs only after the new configuration is in place, so it reads `Env` as usual.

`on_change` registers a synchronous callback for a path and returns a function that removes the registration. It rejects coroutine functions with `TypeError`. Registrations survive reloads and `Env.reset()`.

`from_mqtt` is a static coroutine for startup. It takes a dictionary with `connection`, which must include `hostname`, and `topics`. It loads each retained topic once into its path and then disconnects. It does not keep listening.

Topic names must be exact, so `+` and `#` wildcards are rejected. Each path is slash-separated, or empty for the root. No path may overlap another path.

## Example

```python
from gppu import AppService

def on_lights(changed: frozenset[str]) -> None:
  print(sorted(changed))

unsubscribe = AppService.on_change(on_lights, 'lights')
```
