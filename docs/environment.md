# Env

`gppu.Env` is the global configuration and what any app may look up: the app's `name`, `host`, `platform` (`windows`, `wsl`, `debian`, `macos`), `user`, `home`, `os` and the trace rules. It holds what the app was configured with, not what the app is doing: the configuration changes only when it is loaded again or updated (`update_config`, `from_mqtt`), and `on_change` tells whoever listens; the app's own objects and their state live in the app, never in `Env`.

`Env.from_env(name, app_path)` loads the app's configuration: `<name>.yaml`, or `config.yaml`, found walking up from `app_path`, with its `!include`s. `Env.glob(path)`, `glob_int`, `glob_list` and `glob_dict` read it by a slash path, a string or a `y2path`.

Every object built on `_Config` (every `_Base` and `App`) copies the configuration into its `_my` when it is built, and reads it with `self.my(path)`. An `App` loads `Env` when it is constructed and `Env` is not loaded yet.

One `Env` holds one app's configuration. Several apps sharing one environment, each with its own section, is y2's, not gppu's; the TUI launcher starts each app as its own process, which loads its own `Env`.
