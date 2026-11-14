# Apps

An app receives its environment declaration at construction and reads its own configuration under its known name. All apps in the process share `Env`; `glob` reads the shared configuration. See [configuration.md](configuration.md).

```python
from gppu import App, glob

class Example(App):
    pass

app = Example(environment='Hosts')
app.Info(app.my('greeting'))
assert glob('hosts')
```

## The environment

`Env` is the global singleton environment. App initialization calls `Env.init(environment=...)` before selecting the app's own section. The environment is optional; the first app that declares one loads it, later apps share it, and apps with no loaded environment start with empty configuration. `Env.init` also sets what needs no file: `host`, `os`, `user`, `home`.

## State and Runtime

gppu has no `State` or `Runtime` today. Y2's are the ones in use, and they become gppu's, as Y2's timers did: see `App` below.

Caching is the standard library's: gppu exports `cache`, `lru_cache` and `cached_property` from `functools`. `gppu.data.Cache` is the persistent cache, on disk or in a database.

## The log

`Logger` is the program's log: on the console from gppu's first line, with colours and trace rules, mirrored to a file once `Logger.enable_file_logging(log_file=...)` is called or the configuration names a `log_file`. `Logger.trace_rules` decides which `Debug` lines show; `{'all': True}` shows them all. A line names where it came from: `<module>` for a script, `Class.method` for a method.

## Objects that need more

`_Base` is the parent the environment and the apps share: `mixin_Logger`, the log under the class's own name, with `mixin_Config`, the configuration. `_Base` has no body of its own. An object built on it reads the program's configuration only with `glob(...)`, `glob_int(...)`, `glob_list(...)` and `glob_dict(...)`, never Env's `_my`. Its own configuration, `_my`, starts empty: `self._config_load(source)`, the one loader Env and every app use, lays a YAML file or a loaded section into it, and `self.my(...)`, `self.my_int(...)`, `self.my_list(...)` and `self.my_dict(...)` read it.

- `App` is `_Base` with the data class `_DC`, for a program that is more than a script: what it is constructed with is its data. Its init is cooperative: a class composed after it, as Linked Data's API composes its database or Y2's State its entity, is initialized with what the app does not take.
  - Its timers are Y2's. `app.run_later(callback, delay=..., key=...)` fires the callback once after the delay; arming a key again cancels the timer armed under it. `app.run_every(callback, start=..., interval=...)` fires it at an interval, and a callback that raises still fires the next time. A callback is called with only the keywords it takes.
  - One thread holds every armed timer, and each due callback runs in a thread of its own. `app.timers` holds every armed timer by its id, `app.h_timeouts` those armed under a key. `app.cancel_timer(handle)` cancels one, and `app.cancel_timers()` cancels them all.
- `AsyncApp` composes `App` with `mixin_Stepper`, the YMRO steps, and `mixin_EventLoopBridge`. Construction runs `init`; `await app.run()` runs `init`, `load` and `start` on the app's loop and returns when the work they spawned with `self._spawn(...)` has finished. `app.stop()` cancels it.
  - `init` does light loading, what can be loaded and parsed, as a constructor does.
  - `load` does the heavy loading of data.
  - `start` comes last; at its end the callbacks and timers start working.

An app gives its part of a step by overriding the regular `init`, `load` or `start` and calling super. The double-underscore parts, `__init`, `__load`, `__start` and `__stop`, which YMRO calls once for every class that defines one, are for rare cases: a mixin adding its part without knowing the other classes. A part may be `async def`; YMRO awaits it in an async app.

## Built on AsyncApp

- `MqttApp` (`gppu.iot`): its broker is the configuration's `connection`; it subscribes and starts MQTT at `start`.
- `AppService` (`gppu.iot`, beside `MqttApp`): an `MqttApp` whose part of the environment arrives over MQTT: each retained topic of `config_mqtt/topics`, in the app's own configuration, replaces the path it names in Env, where `glob` reads it. The app's own configuration stays its own. An app acts on new configuration by listening to the same topic; its listener runs after the section is loaded. `await app.from_mqtt()` reads every topic once, then disconnects, and Env keeps what was read.
- `APIApp`: serves its `apis()` on uvicorn at the configuration's `host` and `port`.
- `mixin_Rest`: the universal REST API to any object. It works only in an async app, and no gppu app includes it. See [rest.md](rest.md).
