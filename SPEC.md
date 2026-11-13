# gppu specification

## Env
- Env is a global singleton app. It loads like any app and does not initialize from itself.
- `glob`, `glob_int`, `glob_list` and `glob_dict` are global variables, not properties of a class.
- New configuration is the same event as reload, restart or reset. Configuration is never compared, and nothing listens for its changes.
- The location of the configuration is invisible to an app. There are two environments: Hosts, configured in `RAN/Hosts/_config/config.yaml`, and Creekview, configured in `IoT/_Creekview/_creekview.yaml`. Each comes from its repository.
- There is no topology file.
- The command line overrides an application's behaviour, not the environment.
- Configuration folders hold no Python code.

## Templates
- Configuration can be a template, and an application reads that configuration from the template.
- There are two kinds of templates: Jinja, and the basic template filled by `safe_substitute`.

## State
- State is state: not a `_Base`, with no configuration and no logger.

## Apps
- App's functionality lives in one place, and configuration is read from MQTT in one place.
- AsyncApp does its own init and does not rely on `_Base`.

## Y2
- Y2 only creates apps, and they share one State and one Env.
- Y2's entity is part of gppu.

## Code
- Every new method or class is justified.
- Code uses public methods, never protected members.
