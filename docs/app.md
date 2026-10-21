# Apps

An app is a class built on gppu's app classes: `App` and `CliApp` in `gppu/gppu.py` with `Env`, the apps with steps in `gppu/app.py`. Building the object is what sets it up: by the time it exists, `Env` holds the configuration and the object's `_my` holds a copy of it. What the app does after that is its own methods.

## Configuration on construction

Anything that has `_Config`, `_Base` and every app among them, has `Env` loaded when it exists. If nothing loaded `Env` first, the object loads it from beside its class: `<name>.yaml` or `config.yaml`, searched upward from the class's folder. If `Env` is already loaded, by `Env.from_env(...)`, `Env.from_dict(...)` or an earlier app, the object takes that one. Either way its `_my` is a copy of `Env`, read with `self.my('key')`, `self.my_int(...)`, `self.my_list(...)` and `self.my_dict(...)`.

`_App` adds the name: the name given to the constructor, or the stem of the class's file.

## App

`App` is `_App` with the data class `_DC`: what it is constructed with is its data, and annotated fields read from it. It has no entry method of its own. Construct it and call what the app defines:

```python
from gppu import App, Env, dict_from_yml

class Xmqtt2Mqtt(App):
  def run(self):
    ...

Env.from_dict(dict_from_yml(CONFIG))
Xmqtt2Mqtt(name='xmqtt2mqtt').run()
```

`App` has no steps.

## CliApp

`CliApp` is a command-line utility. It defines `main`, and `MyApp.cli()` builds the app and runs `main`. Its `_my` is the configuration with the command line over it: `--days 7 --dry-run true`, each value a string. What `main` returns is printed as JSON on stdout; logs go to stderr. `CliApp` has no steps.

## AsyncApp and the steps

`AsyncApp` is `_App` composed with `mixin_Stepper`, the YMRO steps, and `mixin_EventLoopBridge`. Construction runs `init`; `await app.run()` runs `init`, `load` and `start` on the app's loop and returns when the work they spawned with `self._spawn(...)` has finished. `app.stop()` cancels it.

- `init` does light loading, what can be loaded and parsed, as a constructor does.
- `load` does the heavy loading of data.
- `start` comes last; at its end the callbacks and timers start working.

An app gives its part of a step by overriding the regular `init`, `load` or `start` and calling super. The double-underscore parts, `__init`, `__load`, `__start` and `__stop`, which YMRO calls once for every class that defines one, are for rare cases: a mixin adding its part without knowing the other classes. A part may be `async def`; YMRO awaits it in an async app.

Any other class that needs the steps composes `_App` with `mixin_Stepper`.

## Built on AsyncApp

- `MqttApp` (`gppu.iot`): its broker is the configuration's `connection`; it subscribes and starts MQTT at `start`.
- `AppService` (`gppu.app_service`): an `MqttApp` that runs all the time and reloads its configuration from MQTT. See [mqtt-config.md](mqtt-config.md).
- `APIApp`: serves its `apis()` on uvicorn at the configuration's `host` and `port`.
- `mixin_Rest`: the universal REST API to any object. It works only in an async app, and no gppu app includes it. See [rest.md](rest.md).
