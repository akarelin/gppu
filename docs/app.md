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

Caching is the standard library's: gppu exports `cache`, `lru_cache` and `cached_property` from `functools`. `gppu.data.Cache` is the persistent cache, on disk or in a database.

## The log

`Logger` is the program's log: on the console from gppu's first line, with colours and the trace rules the environment's `trace_rules` sets. `Logger.trace_rules` decides which `Debug` lines show; `{'all': True}` shows them all. A line names where it came from: `<module>` for a script, `Class.method` for a method.

## Objects that need more

`_Base` is the parent the environment and the apps share: `mixin_Logger`, the log under the class's own name, with `mixin_Config`, the configuration. `_Base` has no body of its own. An object built on it reads the program's configuration only with `glob(...)`, `glob_int(...)`, `glob_list(...)` and `glob_dict(...)`. Its own configuration is its data, the `_DC`'s: `self.my(...)`, `self.my_int(...)`, `self.my_list(...)` and `self.my_dict(...)` read it by path, and an annotated name reads its key directly.

- `App` is `_Base` with the data class `_DC`, for a program that is more than a script: what it is constructed with is its data. `_DC`'s `__init__` is final: it takes what the object is constructed with as its data and runs `init`, which calls every class's private `__init` step once, base first. App's step lays the app's own configuration under that data, so nothing it was constructed with is overwritten: the configuration it is given as `config` (a dict, a YAML file as a `Path`, or YAML text such as a script's MANIFEST), or else the environment's section named as the app. The command line, `sys.argv[1:]`, goes over both. An app a loader made from its row takes the row alone. A class adds its own part as its own `__init`, never by overriding `__init__` or `init`. A class composed with it, as Linked Data's API composes its database or Y2's State its entity, runs its own init first.
- `AsyncApp` composes `App` with `YStart`, the YMRO steps, and `mixin_EventLoopBridge`. Construction runs `init`; `await app.run()` runs `init`, `load` and `start` on the app's loop and returns when the work they spawned with `self._spawn(...)` has finished. `app.stop()` cancels it.
  - `init` does light loading, what can be loaded and parsed, as a constructor does.
  - `load` does the heavy loading of data.
  - `start` comes last; at its end the callbacks and timers start working.
  - Timers are only an async app's. `app.run_later(callback, delay=..., key=...)` fires the callback once after the delay; arming a key again cancels the timer armed under it. `app.run_every(callback, start=..., interval=...)` fires it at an interval, and a callback that raises still fires the next time. A callback is called with only the keywords it takes.
  - A timer is a coroutine on the app's loop, and any thread arms it; its callback runs on one of the loop's worker threads, and one that raises is logged. `app.timers` holds every armed timer's row by its id (its callback's name, its kind, its interval and its next run), `app.h_timeouts` those armed under a key. The handle a timer returns cancels it with `cancel()`; `app.cancel_timers()` cancels them all, and the app's stop does.

An app gives its part of a step by overriding the regular `init`, `load` or `start` and calling super. The double-underscore parts, `__init`, `__load`, `__start` and `__stop`, which YMRO calls once for every class that defines one, are for rare cases: a mixin adding its part without knowing the other classes. A part that is `async def` takes `@sync`: from sync code it runs to the end, and on a running loop it runs as a task.

## Built on AsyncApp

- `mixin_Mqtt`: an async app's MQTT, two methods: `await app.mqtt_listen(callback, topic)` calls `callback(topic, payload)` on each message at the topic, and `await app.mqtt_publish(topic, payload)` publishes. A callback that takes `retained` or `sent` is also told whether the broker kept the message and when it was sent: `mqtt_publish` gives every message its time as the user property `sent`. Each listener gets a topic's retained messages once, the last state there, however many listeners the topic had before it. Its broker is the `mqtt` of the app's configuration, which the client takes as it is, all but `status_topic`: the app's will is `offline` there, and it says `online` there as it connects. It connects in its start step, on MQTT 5, and connects again 5 s after it loses the broker.
- `AppService`: an async app with MQTT whose part of the environment arrives over MQTT: each retained topic of `config_mqtt/topics`, in the app's own configuration, replaces the path it names in Env, where `glob` reads it. The app's own configuration stays its own. An app acts on new configuration by listening to the same topic; its listener runs after the section is loaded. `await app.from_mqtt()` reads every topic once, then disconnects, and Env keeps what was read.
- `APIApp` (`gppu.api`): serves its `apis()` on uvicorn at the configuration's `host` and `port`; FastAPI and uvicorn come with the `ld` extra.
- `mixin_Rest`, deprecated: it does not work and gets in the way. Its one user is Y2's UI API. See [rest.md](rest.md).
