# Apps

An app is a `_DC`: its annotations are its configuration, read inside the app. All apps in the process share `Env`; `glob` reads the shared configuration. See [configuration.md](configuration.md).

```python
from gppu import App, glob

class Example(App):
    greeting: str

    def main(self):
        self.Info(self.greeting)
        assert glob('hosts')

Example().main()
```

## The environment

`Env` is the global singleton environment, made and loaded as gppu is imported; see [configuration.md](configuration.md). It sets what needs no file: `host`, `os`, `user`, `home`.

## State and Runtime

`Runtime` (`gppu.iot`) is Y2's, now gppu's: the program's apps by name, which register with `Runtime.register_app(app)`, the registries they fill (`actions`, `buttons`, `indicators`), and the listeners to events (`listen_event`, `fire_event`), to entity states (`listen_state`, which `state_changed` calls) and to topics (`listen_topic_state`, `topic_changed`). Each listener returns a `ListenerHandle`, whose `cancel()` removes it. `Runtime.restart_app(name)` stops an app and starts a fresh one of the same class, unless the class says `restartable = False`. `Runtime.reset()` cancels every app's timers and empties it. gppu has no `State` today; Y2's is the one in use, and it becomes gppu's, as Y2's timers and Runtime did.

Caching is the standard library's: gppu exports `cache`, `lru_cache` and `cached_property` from `functools`. `gppu.data.Cache` is the persistent cache, on disk or in a database.

## The log

`Logger` is the program's log: on the console from gppu's first line, with colours and the trace rules the environment's `trace_rules` sets. `Logger.trace_rules` decides which `Debug` lines show; `{'all': True}` shows them all. A line names where it came from: `<module>` for a script, `Class.method` for a method.

## Objects that need more

`_Base` is the parent the environment and the apps share: `mixin_Logger`, the log under the class's own name, with `mixin_Config`, the configuration. `_Base` has no body of its own. An object built on it reads the program's configuration only with `glob(...)`, `glob_int(...)`, `glob_list(...)` and `glob_dict(...)`. Its own configuration is its data, the `_DC`'s: `self.my(...)`, `self.my_int(...)`, `self.my_list(...)` and `self.my_dict(...)` read it by path, and an annotated name reads its key directly.

- `App` is `_Base` with the data class `_DC`, for a program that is more than a script: what it is constructed with is its data. `_DC`'s `__init__` is final: it takes what the object is constructed with as its data and runs `init`, which calls every class's private `__init` step once, base first. App's step loads, its environment then its own configuration, and lays the configuration into the data; a class adds its own part as its own `__init`, never by overriding `__init__` or `init`. Env is an App too, the one whose data is the environment. An app reads the command line, `sys.argv[1:]`, unless it is given `argv`. A class composed with it, as Linked Data's API composes its database or Y2's State its entity, runs its own init first.
- `AsyncApp` composes `App` with `YStart`, the YMRO steps, and `mixin_EventLoopBridge`. Construction runs `init`; `await app.run()` runs `init`, `load` and `start` on the app's loop and returns when the work they spawned with `self._spawn(...)` has finished. `app.stop()` cancels it.
  - `init` does light loading, what can be loaded and parsed, as a constructor does.
  - `load` does the heavy loading of data.
  - `start` comes last; at its end the callbacks and timers start working.
  - Timers are only an async app's. `app.run_later(callback, delay=..., key=...)` fires the callback once after the delay; arming a key again cancels the timer armed under it. `app.run_every(callback, start=..., interval=...)` fires it at an interval, and a callback that raises still fires the next time. A callback is called with only the keywords it takes.
  - One thread holds every armed timer, and each due callback runs in a thread of its own. `app.timers` holds every armed timer by its id, `app.h_timeouts` those armed under a key. `app.cancel_timer(handle)` cancels one, and `app.cancel_timers()` cancels them all.

An app gives its part of a step by overriding the regular `init`, `load` or `start` and calling super. The double-underscore parts, `__init`, `__load`, `__start` and `__stop`, which YMRO calls once for every class that defines one, are for rare cases: a mixin adding its part without knowing the other classes. A part may be `async def`; YMRO awaits it in an async app.

## Built on AsyncApp

- `MqttApp` (`gppu.iot`): its broker is the configuration's `connection`; it subscribes and starts MQTT at `start`.
- `AppService` (`gppu.iot`, beside `MqttApp`): an `MqttApp` whose part of the environment arrives over MQTT: each retained topic of `config_mqtt/topics`, in the app's own configuration, replaces the path it names in Env, where `glob` reads it. The app's own configuration stays its own. An app acts on new configuration by listening to the same topic; its listener runs after the section is loaded. `await app.from_mqtt()` reads every topic once, then disconnects, and Env keeps what was read.
- `APIApp`: serves its `apis()` on uvicorn at the configuration's `host` and `port`.
- `mixin_Rest`: the universal REST API to any object. It works only in an async app, and no gppu app includes it. See [rest.md](rest.md).
