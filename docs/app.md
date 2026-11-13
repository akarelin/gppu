# Apps

An app receives its environment declaration at construction and reads its own configuration under its known name. All apps in the process share `Env`; `glob` reads the shared configuration. See [configuration.md](configuration.md).

```python
from gppu import App, glob

class Example(App):
    pass

app = Example(environment={'example': {'greeting': 'Hello'}, 'shared': True})
app.Info(app.my('greeting'))
assert glob('shared') is True
```

## The environment

`Env` is the global singleton environment. App initialization loads its declaration through the shared configuration mixin before selecting the app's own section. Subsequent apps share it. Env also holds what needs no file: `host`, `os`, `user`, `home`.

## State and Runtime

`State` is the program's state: the values its apps know now, apart from the configuration they were given. It is one object, there from import: `State.set(path, value)` writes a value at a slash path and `State.get(path)` reads it.

`Runtime` is the container of the program's apps, one per program. All the apps in it share the one Env and the one State. An app joins with `Runtime.register_app(app)` under its name, and `Runtime.apps` holds them in the order they joined. Apps tell each other with events: `Runtime.listen_event(callback, event)` registers a callback, and `Runtime.fire_event(event, **data)` calls it as `callback(event=..., data=...)`. A callback registered with no event hears every event.

Caching is the standard library's: gppu exports `cache`, `lru_cache` and `cached_property` from `functools`. `gppu.data.Cache` is the persistent cache, on disk or in a database.

## The log

`Logger` is the program's log: on the console from gppu's first line, with colours and trace rules, mirrored to a file once `Logger.enable_file_logging(log_file=...)` is called or the configuration names a `log_file`. `Logger.trace_rules` decides which `Debug` lines show; `{'all': True}` shows them all. A line names where it came from: `<module>` for a script, `Class.method` for a method.

## Objects that need more

`_Base` is the parent the environment and the apps share: `mixin_Logger`, the log under the class's own name, with `mixin_Config`, the configuration. `_Base` has no body of its own. An object built on it reads the program's configuration only with `glob(...)`, `glob_int(...)`, `glob_list(...)` and `glob_dict(...)`, never Env's `_my`. Its own configuration, `_my`, starts empty: `self._config_from_key(key)` lays the configuration's section `key` into it, and `self.my(...)`, `self.my_int(...)`, `self.my_list(...)` and `self.my_dict(...)` read it.

- `App` is `_Base` with the data class `_DC`, for a program that is more than a script: what it is constructed with is its data.
- `AsyncApp` composes `_Base` with `mixin_Stepper`, the YMRO steps, and `mixin_EventLoopBridge`. Construction runs `init`; `await app.run()` runs `init`, `load` and `start` on the app's loop and returns when the work they spawned with `self._spawn(...)` has finished. `app.stop()` cancels it.
  - `init` does light loading, what can be loaded and parsed, as a constructor does.
  - `load` does the heavy loading of data.
  - `start` comes last; at its end the callbacks and timers start working.

An app gives its part of a step by overriding the regular `init`, `load` or `start` and calling super. The double-underscore parts, `__init`, `__load`, `__start` and `__stop`, which YMRO calls once for every class that defines one, are for rare cases: a mixin adding its part without knowing the other classes. A part may be `async def`; YMRO awaits it in an async app.

## Built on AsyncApp

- `MqttApp` (`gppu.iot`): its broker is the configuration's `connection`; it subscribes and starts MQTT at `start`.
- `AppService` (`gppu.iot`, beside `MqttApp`): an `MqttApp` whose configuration arrives over MQTT: each retained topic of `config_mqtt/topics` replaces the configuration path it names, and `AppService.from_mqtt(config)` reads them once at startup.
- `APIApp`: serves its `apis()` on uvicorn at the configuration's `host` and `port`.
- `mixin_Rest`: the universal REST API to any object. It works only in an async app, and no gppu app includes it. See [rest.md](rest.md).
