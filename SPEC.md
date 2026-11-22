# gppu specification

## Env
- Env is a global singleton app. It loads like any app and does not initialize from itself.
- `glob`, `glob_int`, `glob_list` and `glob_dict` are global variables, not properties of a class.
- New configuration is the same event as reload, restart or reset. Configuration is never compared, and nothing listens for its changes.
- The location of the configuration is invisible to an app. There are two environments: RAN, configured in `RAN/_config/config.yaml`, and Creekview, configured in `IoT/_Creekview/_creekview.yaml`. Each comes from its repository.
- The environment, or the part of it an app needs, is read from MQTT on a host that does not have its repository.
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
- Configuration has no repeats where a for loop can produce them.
- The YAML reader reads YAML. Reading a script's inline configuration is not a feature of its own and has no export.
- A script's manifest is read from its source file with a simple regex: a line or two, not pages of parsing code. The manifest sits within the first 4 kilobytes of a known executable file.
- Loading scripts as menu items from the file system is a simple loader, as State's managers load a bunch of objects from a YAML list or from a folder. The manifest tells the loader how to list, execute or instantiate the script.
- Every use of YAML goes through the same parsing process, whatever the text comes from: a file, an include, a script's inline configuration, MQTT.

## State
- gppu offers a simple way for an app to keep its own state, as it offers Env.

## Apps
- App initialization takes its environment; the app already knows its name. An app loads its own configuration, which is independent from the environment.
- App's functionality lives in one place, and configuration is read from MQTT in one place.
- AsyncApp does its own init and does not rely on `_Base`.
- App has no init of its own: it loads through `_DC`'s init.
- Timers exist only in AsyncApp.
- Apps initialize in steps with the tools gppu already has (init, load, start, stop). Construction decides where data is parsed from and in which step.
- TUI apps support inline configs: a script carries its own configuration and manifest, as `examples/sessions_clean.py` does. A Python script assigns its manifest to a global variable.
- Running processes in parallel is not part of a TUI, since a command-line app runs them too. It is an app's method, like its timers (run after, run in, run at).
- Every TUI app is an async app. Every app is a `_DC`, whose data holds everything the app is given, so no app sets its own attributes from it again.
- Configuration is done natively by `_DC`. `_my`, an alternative dictionary on every object, is never used.
- An app does not figure out where its own configuration is. When none is passed to it, gppu finds where it should have been from the app's caller; none of that code is specific to any other code.

## Y2
- Y2 only creates apps, and they share one State and one Env.
- Y2's app is an async app.
- Y2 uses Env; it has no environment of its own.
- Y2's entity is part of gppu.

## Code
- Simplify. Legacy approaches are not kept for backwards compatibility.
- Code stays simple and clearly different from configuration.
- Static code analysis works without observing a running app.
- Exceptions are not swallowed.
- gppu is a class hierarchy of objects with all functionality in methods; it rarely exports standalone functions. A new standalone function needs significant justification.
- Every new method or class is justified.
- gppufs can have its own uri where it needs to extend y2uri.

## Identity
- A UUID is the primary way to refer to any object, internally and externally. The database stores UUIDs, and links are UUIDs.
- A URI is an external reference. A UUID is issued for a URI, which gives a mapping of UUID to URI.
- A user-friendly id is short, unique across the system and usually created by a human: a slug, a namespace, a name or a path. A status is a short lower-case enum rather than an integer key.
- Some objects have a default path that is not stored but can be generated.
- y2uri is a foundation, as `_DC` is: features beyond it come into y2uri or as mixins that a derivative picks.
- Code uses public methods, never protected members.
