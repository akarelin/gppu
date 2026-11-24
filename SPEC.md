# gppu specification

## Env
- Env is a global singleton app. It loads like any app and does not initialize from itself.
- Env is a global system object, created once and hidden from everybody: no program initializes it, uses it or touches it. gppu's own methods use it to do things correctly, such as building paths.
- `glob`, `glob_int`, `glob_list` and `glob_dict` are global variables, not properties of a class.
- New configuration is the same event as reload, restart or reset. Configuration is never compared, and nothing listens for its changes.
- The location of the configuration is invisible to an app. There are two environments: RAN, configured in `RAN/_config/config.yaml`, and Creekview, configured in `IoT/_Creekview/_creekview.yaml`. Each comes from its repository.
- The environment, or the part of it an app needs, is read from MQTT on a host that does not have its repository.
- Apps share the RAN environment. The only other apps are Y2's, and they share Creekview. A third environment, ETL, is foreseen; three is the most.
- The two environments are almost the same, and the library provides very little that is unique to either. A different way of loading, such as from MQTT, is a different init provider for configuration. The hooks are reload, reinitialize from the environment, create state from the environment, and create objects inside the state.
- gppu hard-codes the paths of the two environment files: two lines for the only two use cases. Nothing else finds configuration, and nothing walks up and down folders.
- An environment is a single YAML file. Its path is constructed from the location of the repository.
- Env's load is one YAML load of its file. Env reads no source code, and no other loader is needed.
- There are no sections.
- An app does not deal with its environment: `environment=` on an app is the worst way to initialize code. The environment determines the app, never the other way around.
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
- Repetition in configuration is avoided with includes, include folders, simple `$` templates and YAML anchors. Multi-line Jinja is not needed for it.
- The simplest mechanism that constructs the object and avoids duplication is used: an anchor where an anchor does it, then a `$` template, and Jinja only beyond those.
- An object with properties is better represented in YAML as YAML than as JSON, one field per line, so the next field to fill is in sight; JSON in YAML still has its cases.
- Generated JSON is a template written in YAML, loaded by gppu and written out as JSON, with no code and nothing extra. Jinja never renders JSON text.
- Objects are read by slash paths and `get`.
- A unique human-readable id is a key, not a value: a list whose items each carry a unique id is a dict keyed by it. Statuses and states are short readable text, so a test like "ends with `-rejected`" reads anywhere.
- UI renders with gppu's Jinja, not a templating of its own. UI is periphery; its templates move toward one way of rendering.
- A template file keeps its destination's extension, such as `.html` or `.md`, never `.j2`. OpenViking's Markdown templates are an example of Jinja used correctly.
- Jinja constructs living objects, `_DC`s, never dicts, and never concatenates tokens to create JSON. In a YAML template, curly braces mean Jinja and nothing else: flow-style `{…}` is embedded JSON and makes YAML not YAML.
- Jinja in configuration is an expression in `{{ }}`. Statements in `{% %}` are a special case that is almost never used, and multi-line Jinja is usually a fail.
- Objects are created through configuration: `_DC` initializes them natively, and a class does not redo its initialization from zero.
- An object's identity comes from configuration; no code creates it, and Jinja has nothing to do with it. The kind of object being constructed is always known, because the construction is passed in.
- An object's data is its representation, as YAML, JSON or an MQTT payload: an input template turns what arrives into data, and an output template writes data out. A simple callback needs no object unless it has state.
- Some functionality is declared in code rather than configuration. A class per kind of equipment is fine where there are one or two of each, such as Y2's AV classes (an LG TV, a Denon receiver), whose configuration would be awkward. What exists in hundreds, such as light switches, scenes and Insteon devices, comes from templates.
- Templates also serve compilers: Y2 compiles its configuration into Insteon's, MQTT's and Home Assistant's, and some compilers write text files. A generated file, such as the shades table, is semi-static: cache and configuration at once, not written by a human, regenerated on rare occasions, saved and included into the configuration correctly.
- A host is declared by its name, and everything else about it, its address, its MAC and the rest, follows from that name. RAN's hosts, which Preservator and fleet management use, and Creekview's hosts, which IoT uses, are separate tables for now. Looking a host up works the same way in both, and how the two environments reference hosts converges over time.
- Correct configuration generates correctly working objects, so static analysis is enough to check it; runtime analysis is not needed.
- A loader creates a bunch of objects from a path into the configuration and some parameters of the object. At the end of the path is a dict or a list, whether written in YAML, generated by Jinja, included, or a folder include.
- The code distinguishes when Jinja is resolved, and with which values.
- The YAML reader reads YAML. Reading a script's inline configuration is not a feature of its own and has no export.
- A script's manifest is read from its source file with a simple regex: a line or two, not pages of parsing code. The manifest sits within the first 4 kilobytes of a known executable file.
- Loading scripts as menu items from the file system is a simple loader, as the runtime loads a bunch of objects from a YAML list or from a folder. The manifest tells the loader how to list, execute or instantiate the script.
- Every use of YAML goes through the same parsing process, whatever the text comes from: a file, an include, a script's inline configuration, MQTT.

## State
- gppu offers a simple way for an app to keep its own state, as it offers Env.
- State is a shared object, a trivial `_DC`: a lookup from an entity's identity to the entity object, reached through the entity or through the runtime. gppu provides state and its persistence, and persistence works as it should. Y2's version of state, with its caching, stays in Y2 for now.

## Apps
- An app already knows its name. An app loads its own configuration, which is independent from the environment.
- App's functionality lives in one place, and configuration is read from MQTT in one place.
- AsyncApp does its own init and does not rely on `_Base`.
- App has no init of its own: it loads through `_DC`'s init.
- Timers are their own mixin, separate from AsyncApp's lifecycle, with two methods: `run_later` and `run_every`.
- gppu holds what a command-line app needs: it starts, does something and terminates, with no parameters. `gppu.app` holds what is more than that: async apps, timers, UIs, fleet management and the runtime Y2 runs on, shared by every app.
- Every app works with no parameters: it knows enough about itself to log its output and know what it does. A navigator over gppufs from a root is a few lines.
- A trivial utility stays trivial: a launcher, a TUI or fleet management runs it with one click, and no sidecar file sits beside it.
- Apps initialize in steps with the tools gppu already has (init, load, start, stop). Construction decides where data is parsed from and in which step.
- TUI apps support inline configs: a script carries its own configuration and manifest, as `examples/sessions_clean.py` does. A Python script assigns its manifest to a global variable.
- An app comes in every size: an entity can be an app, a whole CLI can be an app, and a container app runs small apps and tends their state. Apps nest; a runtime app or a container app holds others. A bunch of apps is created from a YAML list, and the container tends the state of those apps, including apps with a simplified lifecycle that start often, such as data loads and processes.
- The command line, MQTT and container apps come for free. An app does not know it has an MQTT last will or an online status: that is configured and done for it. Its client id comes from its name, which configuration gives it.
- A connection string, such as Postgres's or MQTT's, is a one-line value in the global configuration, and an app reads it by its key.
- Hosting and spawning processes, with their completion callbacks, is one simple shared mechanism in gppu, used by fleet management and Y2 alike.
- Running processes in parallel is not part of a TUI, since a command-line app runs them too. It is an app's method, like its timers (run after, run in, run at).
- Refreshing belongs to the runtime and is configured; callbacks sit on a different level. Every object refreshes in the one way known for it, and every way is a simple timer or listener: on a schedule, after a timeout following an event, on a state change, when a state has stayed the same for a period, or when no events of a kind have come for a period.
- Every TUI app is an async app. Every app is a `_DC`, whose data holds everything the app is given, so no app sets its own attributes from it again.
- An app is an assembly of mixins: `_Base` puts the basic two together, and an app picks async, TUI or whatever else it needs.
- A simple CLI app has no code to find where it was started or where its configuration is, and invents no command line of its own; it is aware of the topology. Nothing passes paths to construct something, and nothing needs the user's home.
- Every object is a `_DC`, and everything happens in its initialization lifecycle. Lifecycles interlock through a correct sequence of small, one-line initialization steps, and that sequence creates the whole functionality of the system; neither code nor configuration spells it out. The object hierarchy is shallow, from simplest to most complex, and each initialization sequence is short.
- An object's `__init__` is final and no class overrides it: it takes the object's data and runs its lifecycle. A class adds its own private steps (`__init`, `__load`, `__start`, `__refresh`, `__publish`), a line or two each, and each step runs for every class from base to most specific, once. This is Y2's `YData` and `_YMRO` (`y2core.py` at `bd717a3`). The lifecycle classes keep their names there, `YInit`, `YLoad` and `YStart`, and no level of inheritance is added to them.
- An object reads its configuration as `self.name`, never as `self.my('name')`. No app parses YAML text or reads a configuration it declared for itself, and no YAML file beside the code duplicates or contradicts it.
- A list of objects, such as the hosts, is created by a loader from the environment, where it already is.
- Configuration is done natively by `_DC`. `_my`, an alternative dictionary on every object, is never used.
- An app does not figure out where its own configuration is. When none is passed to it, gppu finds where it should have been from the app's caller; none of that code is specific to any other code.

## Y2
- Y2 only creates apps, and they share one State and one Env.
- Y2's app is an async app.
- Y2 uses Env; it has no environment of its own.
- Y2's entity is part of gppu.
- Y2 was originally part of gppu. Only entity support, the Y2 entity and below, is specific to Y2; everything else is generic and is gppu's, so Y2's own code is slim.
- Y2's runtime, Y2 entity and Y2 group are one step on top of gppu, and they are correct. There is no state manager: it is a kind of runtime, the async app, initialized from configuration, which knows what kinds of objects it makes and where it loads them from (its `key`), and kicks off their lifecycle. Only a manager that handles hardware, such as Hue's, has code of its own; GSM and ISM have very little. A class full of special cases, such as an AV device, stays a valid Y2 entity or group and never does what gppu does.
- A device class builds on its base classes. What every entity shares is the base's, in one place, and a device class adds only its device's own calls.
- A class that only says what kind of entity something is has `pass` for its body.

## Library and periphery
- No functionality has two implementations. It is either gppu's, and every app uses it, or an app's own. An app that does its own thing is named and known, to be refactored later.
- An app with a unique mechanism that does one thing differently, such as W11 or the status line, is not refactored just for that.
- An unfinished migration between gppu and the periphery is settled in one direction: into gppu, staying in gppu, or staying with the app. The downstream users decide it, and Alex decides where he has an opinion.
- An app is not universal: it reads its own configuration well, not any configuration. A simple app is half a page of code, a complex one a full page.
- Refactoring goes top down and in passes, deciding for each piece whether it belongs in code, in a template or in configuration, and at which level.

## Code
- Simplify. Legacy approaches are not kept for backwards compatibility.
- Code stays simple and clearly different from configuration.
- Static code analysis works without observing a running app.
- Exceptions are not swallowed.
- Imports sit at the top of a module; no module is imported inside a function.
- gppu is a class hierarchy of objects with all functionality in methods; it rarely exports standalone functions. A new standalone function needs significant justification.
- Every new method or class is justified.
- gppufs can have its own uri where it needs to extend y2uri.

## Release
- gppu stays on 3.7.11; 3.8.0 is far on the horizon. A build builds the current code under that version, with no increments, so `pip install -r requirements` gets the one latest.
- `pip show gppu` shows when the build was made and Alex's information from GitHub.
- Betas are disabled.

## Identity
- A UUID is the primary way to refer to any object, internally and externally. The database stores UUIDs, and links are UUIDs.
- A URI is an external reference. A UUID is issued for a URI, which gives a mapping of UUID to URI.
- A user-friendly id is short, unique across the system and usually created by a human: a slug, a namespace, a name or a path. A status is a short lower-case enum rather than an integer key.
- Some objects have a default path that is not stored but can be generated.
- y2uri is a foundation, as `_DC` is: features beyond it come into y2uri or as mixins that a derivative picks.
- Code uses public methods, never protected members.
- A limited set of cases is hard-coded: two cases in two lines, and a third is decided when it appears. Nothing universal is built for them. Dicts and lists are handled specifically, which is why there are `my_int` and `my_float` and nothing more; there is no recursion, no self-reference and no passing objects back and forth.
- The command line is not a separate kind of app. Every app takes the command line, which always works by default and is never suppressed.
- An app run with no parameters does something useful; it is not a dry run, and nobody needs to know which parameters to pass.
- A Python script runs from the host's one `.venv`. A script that imports gppu has everything it needs and always starts.
- Logging works without special error handling around it: no code logs an error outside the logger, and tracing carries no error handling of its own. Dumping is the one exception: a dump that fails writes its error to a file beside it, because no logger may be available where it runs, as in an asynchronous callback.
- An object does not need a configuration key of its own for MQTT.
- Preservator is the use case of a small CLI app that works trivially.
