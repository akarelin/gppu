# Apps

Any Python program that imports gppu is already an app. Importing gppu gives it its environment, `Env`, which it never needs to know of: `Info`, `Warn`, `Error`, `Debug` and `glob` are Env's members promoted to module names. [examples/basic.py](../examples/basic.py) is the whole of it:

```python
from gppu import Env, Info, Logger, glob

Info('started on', Env.host)
if glob('trace'): Logger.trace_rules['all'] = True
if glob('log_file'): Logger.enable_file_logging(log_file=glob('log_file'))
```

## The environment

`Env` is an app of a special kind: static, global, one per program. Its first read of the configuration loads it: `<name>.yaml` or `config.yaml`, searched upward from the program's folder, named after the program; a program with no such file runs without one. The command line goes over it: `--key value` sets that key, a bare `--flag` sets it to True, a slash path names a nested key; other arguments are the program's own. Env also holds what needs no file: `host`, `platform`, `os`, `user`, `home`.

## The log

`Logger` is the program's log: on the console from gppu's first line, with colours and trace rules, mirrored to a file once `Logger.enable_file_logging(log_file=...)` is called or the configuration names a `log_file`. `Logger.trace_rules` decides which `Debug` lines show; `{'all': True}` shows them all. A line names where it came from: `<module>` for a script, `Class.method` for a method.

## Objects that need more

`_Base` is the parent the environment and the apps share: `mixin_Logger`, the log under the class's own name, with `mixin_Config`, the configuration. An object built on it is named as given or after the program, and its `_my` is a copy of Env, read with `self.my(...)`, `self.my_int(...)`, `self.my_list(...)` and `self.my_dict(...)`.

- `App` is `_Base` with the data class `_DC`, for a program that is more than a script: what it is constructed with is its data.
- `CliApp` runs `main` and prints what it returns as JSON: `MyApp.cli()`.
- `AsyncApp` composes `_Base` with `mixin_Stepper`, the YMRO steps, and `mixin_EventLoopBridge`. Construction runs `init`; `await app.run()` runs `init`, `load` and `start` on the app's loop and returns when the work they spawned with `self._spawn(...)` has finished. `app.stop()` cancels it.
  - `init` does light loading, what can be loaded and parsed, as a constructor does.
  - `load` does the heavy loading of data.
  - `start` comes last; at its end the callbacks and timers start working.

An app gives its part of a step by overriding the regular `init`, `load` or `start` and calling super. The double-underscore parts, `__init`, `__load`, `__start` and `__stop`, which YMRO calls once for every class that defines one, are for rare cases: a mixin adding its part without knowing the other classes. A part may be `async def`; YMRO awaits it in an async app.

## Built on AsyncApp

- `MqttApp` (`gppu.iot`): its broker is the configuration's `connection`; it subscribes and starts MQTT at `start`.
- `AppService` (`gppu.app_service`): an `MqttApp` that runs all the time and reloads its configuration from MQTT. See [mqtt-config.md](mqtt-config.md).
- `APIApp`: serves its `apis()` on uvicorn at the configuration's `host` and `port`.
- `mixin_Rest`: the universal REST API to any object. It works only in an async app, and no gppu app includes it. See [rest.md](rest.md).
