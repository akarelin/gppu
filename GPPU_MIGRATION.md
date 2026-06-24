# gppu async and IoT migration

This is a breaking simplification. Update `gppu` and its downstream applications in the same deployment.

## Public surface

Import these names from `gppu`, not `gppu.iot` and never by a leading-underscore implementation name:

| Need | API |
|---|---|
| Standalone asyncio lifecycle | `AsyncApp` |
| Standalone MQTT service | `MqttApp` |
| MQTT in a framework-owned loop | `mixin_Mqtt` + `EventLoopBridge` |
| Per-device async transport | `SerializedControl` |
| Text/bytes HTTP | `HTTPControl` |
| JSON-over-HTTP | `JSONHTTPControl` |

Removed APIs: `aYMRO`, `aYInit`, `aYLoad`, `aYStart`, `aYStepper`, `mixin_aStepper`, `mixin_Timers`, `protocol_Async`, `serve_task()`, `initialize()`, `_IORuntime`, `_io_host`, `_SerialControl`, and `_SerialHTTPControl`.

## Upgrade sequence

1. Update `gppu` and all consumers atomically; there are no compatibility aliases for the removed APIs.
2. Convert standalone services to `AsyncApp` or `MqttApp`.
3. Convert framework-owned clients to `EventLoopBridge` + `mixin_Mqtt`.
4. Put one `SerializedControl` specialization on each class representing one physical device.
5. Separate text HTTP from JSON explicitly.
6. Compile and run the focused concurrency/reconnect tests listed below before deployment.

Useful audit:

```bash
rg -n 'aYMRO|aYInit|aYLoad|aYStart|aYStepper|mixin_aStepper|mixin_Timers|protocol_Async|serve_task|\.initialize\(|_IORuntime|_io_host|_SerialControl|_SerialHTTPControl' .
rg -n 'from gppu\.(app|iot) import .*_' .
```

## Standalone MQTT services

Replace order-sensitive multiple inheritance and async YMRO hooks:

```python
class Service(AsyncApp, mixin_Mqtt):
  def __init__(self): ...
  async def __start(self): ...

asyncio.run(Service(...).initialize())
```

with:

```python
from gppu import MqttApp

class Service(MqttApp):
  def setup(self) -> None:
    self.connection = self.data['connection']

  async def subscribe(self) -> None:
    await self.mqtt_listen(self._on_message, 'input/#')

  def _mqtt_tasks(self):
    return [self._poll_loop()]

asyncio.run(Service(...).run())
```

Rules:

- Do not add an application `__init__`; use synchronous `setup()` for derived and mutable runtime state.
- `setup()` runs during construction after `App`/`_DC` initialization. Do not perform async I/O there.
- `subscribe()` runs once before the reconnect loop starts. Registration is replayed after every reconnect.
- `_mqtt_tasks()` takes no client argument. It runs after each successful connection and must return newly created coroutine objects.
- A connection-scoped task must release HTTP sessions, controller objects, and similar resources in `finally` because it is cancelled on broker disconnect.
- A non-MQTT exception in the dispatch or connection task group terminates the service. Do not suppress programming errors as reconnect noise.
- `.run()` replaces `.initialize()`.

## Standalone non-MQTT services

```python
from gppu import AsyncApp

class Service(AsyncApp):
  def setup(self) -> None:
    ...

  async def start(self) -> None:
    self._spawn(self._serve())

asyncio.run(Service(...).run())
```

`run()` opens one `asyncio.TaskGroup`. `_spawn()` is valid only while that group is active. A task failure cancels its siblings and terminates the service. `stop()` cancels tasks created through `_spawn()`.

## MQTT in an externally managed loop

Use lifecycle-neutral `mixin_Mqtt` with `EventLoopBridge`. The framework owns startup, shutdown, and the loop:

```python
from gppu import EventLoopBridge, mixin_Mqtt

class Host(EventLoopBridge, mixin_Mqtt):
  def _get_loop(self) -> asyncio.AbstractEventLoop:
    return self.framework.loop

  def _spawn(self, coroutine):
    return self.schedule(coroutine)

  def start_transport(self) -> None:
    self.connection = {...}
    self._start_mqtt()
```

Use:

- `schedule(coroutine)` when a coroutine object already exists.
- `submit(async_function, *args, **kwargs)` for non-blocking function submission.
- `call(async_function, *args, **kwargs)` only from a non-loop thread that must synchronously receive the result.
- `on_loop()` when a synchronous facade must choose between submission and blocking.

`call()` rejects the target event-loop thread rather than deadlocking it. Framework callbacks that may block must run in the framework executor, not on its event loop.

## Per-device async controls

A class representing one physical device inherits `SerializedControl`, or one HTTP specialization:

```python
from gppu import SerializedControl

class Receiver(SerializedControl):
  def command(self, value: str) -> str:
    return self._control_call(self._command_async, value)

  async def _command_async(self, value: str) -> str:
    ...
```

Each instance lazily owns one `asyncio.Lock`. Calls for the same device serialize; distinct device instances remain concurrent on the shared control-loop thread.

Do not put `SerializedControl` on:

- a StateManager containing multiple physical devices;
- every child/outlet of the same physical device;
- a generic global host object;
- a class whose operations already run exclusively on its framework-owned loop.

For a fire-and-forget poll:

```python
def refresh(self, **data) -> None:
  self._control_submit(self._refresh_async, data)

async def _refresh_async(self, data: dict) -> None:
  try:
    ...
  except Exception as error:
    self.api.Error(..., error)
```

The returned future is intentionally not retained, so the coroutine itself must log operational failures.

Device connection/client caches belong on that same physical-device instance. Avoid module-global host caches; they obscure ownership and can bypass per-instance serialization.

## HTTP versus JSON-over-HTTP

`HTTPControl` transports `str | bytes` and returns decoded response text:

```python
from gppu import HTTPControl

class Display(HTTPControl):
  def send(self, command: str) -> bool:
    return self._http_post(
      self.url,
      command + '\n',
      headers={'Content-Type': 'application/octet-stream'},
    ) is not None
```

`JSONHTTPControl` is the explicit JSON layer:

```python
from gppu import JSONHTTPControl

class Hub(JSONHTTPControl):
  def set_value(self, value: int) -> dict | None:
    response = self._json_put(self.url, {'value': value})
    return response if isinstance(response, dict) else None
```

Rules:

- Do not pass a `dict` to `_http_post()` or `_http_put()`; use `_json_post()` or `_json_put()`.
- HTTP status failures, transport failures, text decode failures, and invalid response JSON return `None`.
- A valid JSON `null` also decodes to `None`; narrow the expected response with `isinstance()` where that distinction matters.
- JSON responses may be scalars or lists. Do not annotate every endpoint as `dict` without checking it.
- Inside a coroutine already entered through `_control_call()` or `_control_submit()`, call `_http_request_async()` or `_json_request_async()` directly. A synchronous wrapper there would try to reacquire the same non-reentrant lock.

## Serial and protocol-specific controls

The generic serial layers are removed. Keep protocol concerns in the integration:

- framing and terminators;
- banners and handshakes;
- response parsing;
- retry/reconnect behavior;
- protocol-specific logging.

Only loop bridging and per-device serialization belong in `gppu`.

## Configuration annotations

`_DC` now recognizes generic built-in annotations, including future-annotation strings:

```python
connection: dict[str, object]
topology: list[dict[str, object]]
```

Use these properties directly. `setup()` should create only derived or mutable runtime state, not parallel copies of configuration fields.

## AppDaemon/Y2 rules

- AppDaemon owns its event loop. Bind `EventLoopBridge._get_loop()` to `self.AD.loop` for AppDaemon-native MQTT work.
- Physical device I/O uses `SerializedControl`'s dedicated loop.
- Publish/state/service work that relies on AppDaemon's synchronous wrappers runs in `self.AD.executor`.
- Poll methods generally use `_control_submit()` so the StateManager worker returns immediately.
- Commands that require completion use `_control_call()` from an executor thread.
- Child entities call methods on their physical-device parent; they do not own independent transport locks or clients.

## Verification

At minimum:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m unittest -v tests/test_async_iot.py

git diff --check
```

For a source-only compile without creating bytecode caches:

```bash
python - <<'PY'
from pathlib import Path

for path in Path('.').rglob('*.py'):
  if path.as_posix() == 'any2mqtt/brultech/btmon.py': continue  # retained Python 2 collector
  if '.git' not in path.parts and '__pycache__' not in path.parts:
    compile(path.read_text(encoding='utf-8'), str(path), 'exec')
PY
```

The regression suite covers:

1. same-device operations never overlap;
2. different device instances can overlap and use the same control-loop thread;
3. `EventLoopBridge.call()` rejects its target loop;
4. text HTTP returns text and JSON HTTP performs explicit serialization;
5. `_mqtt_tasks()` creates fresh tasks after reconnect and connection-scoped cleanup runs;
6. MQTT subscription QoS is replayed correctly.

The downstream review must additionally confirm that imports have no service-start side effects and framework-facing work runs on the intended loop or executor.
