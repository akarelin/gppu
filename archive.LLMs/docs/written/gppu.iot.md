<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/iot.py fc4df4ef57d3d5769eec0b9919055340c415e5d6 -->
The `gppu.iot` module provides IoT value types, an MQTT transport that reconnects after errors, and controls that let synchronous code make HTTP calls through one shared event loop.

The module has three parts. `y2eid` is an entity identifier in the form `domain.slug@namespace`, with the namespace defaulting to `yala` and the domain to `entity`. The module also registers `y2eid`, `y2topic`, `y2path` and `y2uri` in gppu's configuration type maps, so configuration can declare values of these types.

The MQTT transport comes in two forms. `MqttApp` is an `AsyncApp` with one reconnecting client, and it owns its lifecycle, so a standalone service runs it with `run()`. `mixin_Mqtt` provides the same transport to a host that owns its own loop and lifecycle, as Y2 does. The host supplies `connection`, `Info`, `Warn` and `_spawn(coro)`, calls `_start_mqtt()` at startup, and cancels its tasks at shutdown. Subscriptions persist across reconnects and are replayed on each new connection. Incoming messages are matched against MQTT wildcard patterns, and their callbacks run one at a time. Payloads that look like JSON are parsed before delivery. `_mqtt_tasks()` returns coroutines that are started fresh on each connection. Publishes made while disconnected are discarded.

The controls bridge synchronous callers to one daemon thread that runs an asyncio loop. All instances share that thread, and each instance serializes its own controls with a lock. `SerializedControl` provides the base mechanism. `HTTPControl` adds `_http_get`, `_http_put` and `_http_post`, which return the response text, or `None` on a request or response failure. `JSONHTTPControl` adds `_json_get`, `_json_put` and `_json_post`, which send and parse JSON. They return `None` when there is no response or the body is not JSON. A subclass sets `_http_timeout` (default 10), `_http_headers` and `_http_ssl` as class attributes.

A standalone service subclasses `MqttApp`. The broker mapping comes from the configuration's `connection`. Override `subscribe()` to register callbacks, which take `(topic, payload)` and may be sync or async:

```python
import asyncio
from gppu import MqttApp

class MyApp(MqttApp):
  async def subscribe(self) -> None:
    await self.mqtt_listen(self.on_message, 'example/topic')

  async def on_message(self, topic, payload) -> None:
    await self.mqtt_publish('example/reply', payload)

asyncio.run(MyApp().run())
```
