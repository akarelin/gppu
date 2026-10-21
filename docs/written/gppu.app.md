<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/app.py 0ff3e28ef298e1fcb080f0c8676c5abe2e3da376 -->
gppu.app holds the applications that run in lifecycle steps: init, load, start and stop. Plain applications with no steps (Env, _Base and App) live in gppu.gppu. For a Textual interface use gppu.tui.TUIApp, and for MQTT use gppu.iot.MqttApp.

## How the pieces work together

The YMRO (Y2 Method Resolution Order) machinery runs each class's part of a step in base-first order. A class contributes a part by defining a method named `__init`, `__load`, `__start` or `__stop`, either sync or async. The step methods themselves (`init`, `load`, `start`, `stop`) are final. `mixin_Stepper` gives a class these steps. `init` runs on construction, and `load` and `start` run in `run()`. `stop` clears the loaded and started flags.

`AsyncApp` composes `_Base` with the steps and is the base for long-lived asyncio services. Its `run()` coroutine runs init, load and start on the running loop. It returns when all work added with `_spawn(coroutine)` has finished, and `stop` cancels that background work. `AsyncApp` is also a `mixin_EventLoopBridge`, so threads outside the loop can `schedule` or `submit` coroutines onto it, or `call` one and wait for its result. `call` refuses to run on the loop's own thread, and `on_loop` reports whether the caller is on that thread.

`mixin_Rest` exposes an application's own public members over HTTP. Fields and properties are read, and methods are called with the JSON body as keyword arguments. Only classes defined under `Env.app_path` are exposed, and private names and the step methods are excluded. It is not included by default. A class composes it before its application base, and it works only in an `AsyncApp`. Override `rest_registries` to name the objects it serves. The HTTP host supplies the listener and JSON serialization, and calls `rest_manifest`, `rest_objects`, `rest_read` and `rest_call`.

`APIApp` is an `AsyncApp` that serves HTTP with uvicorn at the `host` and `port` of its configuration. Override `apis()` to map each path to the ASGI app served there. Work needed before serving belongs in `load`, because the server starts at the end of `start`. FastAPI and uvicorn come with the `ld` extra.

## Use

Construction runs `init`, and `run()` runs `load` and `start` on the running loop:

```python
import asyncio
from gppu.app import AsyncApp

class MyApp(AsyncApp):
  pass

asyncio.run(MyApp().run())
```
