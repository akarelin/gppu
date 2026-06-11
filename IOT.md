# gppu.iot - IoT Primitives & MQTT Plumbing

`gppu.iot` provides the y2 token-list types used across the Y2/any2mqtt ecosystem (topics, slugs, entity ids) and the shared mqtt service plumbing for the any2mqtt transform services (brul2mqtt, motion2mqtt, ...). The library is not a service: each service owns its broker login, identifier, and `status/<service>` LWT.

```python
from gppu.iot import y2list, y2path, y2topic, y2slug, y2eid
from gppu.iot import mqtt_connstring, MqttMixin, Transformer
```

All names are also re-exported from the top-level `gppu` package.

`aiomqtt` (and its `paho-mqtt` dependency) is optional — install `gppu[mqtt]` for the mqtt classes. The y2 types work without it.

## y2 Types

Token-joined string/list hybrids built on `UserList`: equal to (and hashable as) their string form, while staying list-manipulable.

| Type | Token | Purpose |
|------|-------|---------|
| `y2list` | `""` (or any) | Base class: `head`/`tail`, `pophead`/`poptail`, `popprefix`/`popsuffix`/`popxfix`, `startswith`/`endswith` (token-aware, accept `_`/`/`-delimited forms and lists), `extract`, `discard`, `iadd` |
| `y2path` | `/` | Slash-joined path; constructor joins any mix of strings/lists/y2lists |
| `y2topic` | `/` | `y2path` + `is_wildcard()` (`#`/`+` detection) — the mqtt topic type |
| `y2slug` | `_` | Underscore-joined slug; strips any `@ns` suffix |

`y2eid` — entity id of the form `domain.slug@ns` (defaults: `entity`, `yala`). Accepts strings, dicts with `entity_id`, other y2eids, or objects with `entity_id`+`namespace`/`ns` or `seid`. Exposes `domain`, `slug`, `ns`, `entity_id`, `seid`, `head`/`tail`; truthy only when fully parsed.

`y2eid` and `y2topic` are registered in `_DC`'s type map, so they work as `_DC` field annotations.

## mqtt_connstring

```python
conn = Env.glob_dict('sensors/connection')
connstring = mqtt_connstring(conn)     # dict: aiomqtt.Client(**connstring)
```

Plain dict filter — keeps exactly the `aiomqtt.Client` kwargs (`hostname`, `port`, `username`, `password`, `identifier`) from a yaml `connection:` block, dropping service-level keys (`status_topic`, `listen`, ...).

## MqttMixin

Reconnecting aiomqtt client with callback dispatch. A service mixes it in, sets `self.connstring`, and calls `_mqtt_init()` during init.

| Method | Purpose |
|--------|---------|
| `mqtt_subscribe(cb, topic)` / `mqtt_unsubscribe(cb, topic)` | Register/remove an async callback `cb(topic, payload)`; subscribes/unsubscribes on the broker as needed |
| `clear_listeners(topic)` | Drop all callbacks for a topic |
| `mqtt_publish(topic, payload, retain, expiry=None, qos=0, **data)` | dict payloads are JSON-encoded, everything else `str()`-ed. `expiry` sets MQTT5 message-expiry (seconds); extra kwargs become MQTT5 UserProperty pairs |
| `mqtt_connect(client)` / `mqtt_disconnect()` | Connection lifecycle: replay subscriptions on (re)connect, clear the client on drop |
| `_mqtt_run()` | Forever-loop: connect, dispatch, reconnect after 5s on `MqttError` |

Dispatch parses JSON payloads (`{`-prefixed), matches exact topics or `prefix/#` patterns, and runs callbacks serialized under a lock; callback exceptions are logged, never fatal.

## Transformer

`App + MqttMixin + mixin_Stepper` — a config-driven scalar transform service stage: subscribes to `connection.listen` patterns, applies `rules` (cascading sum/difference maps over topic groups, optional `sign_flip`), and republishes to `dest_prefix/<name>` topics, debounced (`DEBOUNCE` = 10s). Maintains a `status_topic` LWT (`online`/`no-data`/`offline`) with a no-data watchdog (`NODATA_TIMEOUT` = 60s).

Config shape (one transformer per entry, e.g. `power/brultech/transforms` in the Creekview topology):

```yaml
- connection:
    hostname: mqtt.example
    port: 1883
    username: brul2mqtt
    password: ...
    identifier: brul2mqtt
    status_topic: status/brul2mqtt
    listen: [systems/panel/#]
  rules:
    - source_prefix: systems/panel/A
      dest_prefix: power/panel
      processors: [sign_flip]
      map:
        feed: [feed]                # sum of inputs
        rack: [[rack1], [rack2]]    # first group minus the rest
```

See `IoT/any2mqtt/brultech/brul2mqtt.py` (runs Transformers directly) and `IoT/any2mqtt/motion2mqtt.py` (custom MqttMixin service) in the RAN repo for real usage.
