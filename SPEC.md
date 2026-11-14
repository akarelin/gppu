# gppu specification

## Env
- Env is a global singleton app. It loads like any app and does not initialize from itself.
- `glob`, `glob_int`, `glob_list` and `glob_dict` are global variables, not properties of a class.
- New configuration is the same event as reload, restart or reset. Configuration is never compared, and nothing listens for its changes.
- The location of the configuration is invisible to an app. There are two environments: RAN, configured in `RAN/_config/config.yaml`, and Creekview, configured in `IoT/_Creekview/_creekview.yaml`. Each comes from its repository.
- Apps share the RAN environment. The only other apps are Y2's, and they share Creekview.
- Configuration is not found by hard-coding or by walking up and down folders.
- An environment is a single YAML file. Its path is constructed from the location of the repository.
- An app declares RAN or IoT; the rest is determined from that declaration.
- There is no topology file.
- The command line overrides an application's behaviour, not the environment.
- Configuration folders hold no Python code.
- An app does not require an environment. The basic.py example uses RAN and its debug logging.

## Templates
- Configuration can be a template, and an application reads that configuration from the template.
- Loading fills the Jinja that reads only the configuration (`glob`, `glob_int`, `glob_list`, `glob_dict`). Jinja that reads the host, the platform or a row stays as written for the app that renders it per host, and `$` text stays as written.
- There are two kinds of templates: Jinja, and the basic template filled by `safe_substitute`. Both are gppu's; an app has no template engine of its own.
- Generators are gone; Jinja replaced them.
- A template is a named template, and `template:` names it. Templates are simple inline functions that return lists, dicts or scalars to be merged into dicts; they return objects, not text.
- YAML anchors are YAML, resolved by the YAML standard. They are not Jinja.

## State
- State is state: not a `_Base`, with no configuration and no logger.

## Apps
- App initialization takes its environment; the app already knows its name. An app loads its own configuration, which is independent from the environment.
- App's functionality lives in one place, and configuration is read from MQTT in one place.
- AsyncApp does its own init and does not rely on `_Base`.
- TUI apps support inline configs: a script carries its own configuration and manifest, as `examples/sessions_clean.py` does. A Python script assigns its manifest to a global variable.
- Running processes in parallel is not part of a TUI, since a command-line app runs them too. It is an app's method, like its timers (run after, run in, run at).
- Every TUI app is an async app. Every app is a `_DC`, whose data holds everything the app is given, so no app sets its own attributes from it again.

## Y2
- Y2 only creates apps, and they share one State and one Env.
- Y2's entity is part of gppu.

## Code
- Every new method or class is justified.
- Code uses public methods, never protected members.
