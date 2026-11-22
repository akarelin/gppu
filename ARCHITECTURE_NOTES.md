# gppu: environment, state, runtime

Notes of an agent session, 2026-11-21. The first part is what Alex said in that session, as plain statements in his terms. The second part is what the agent found in the running code, each with its location. Nothing here comes from commit messages, `SPEC.md`, plans, docs or tests.

# What Alex said

## The three objects
- There are only three things to think of: environment, state and runtime. Everything is defined in those three. Nothing else is needed. Everything else is access.
- They are three objects, and they are to be understood exactly, before anything else about gppu, Y2 or an app is explained. Conclusions drawn without them do not stand.
- Runtime and configuration are sufficient for the majority of functionality.
- gppu was small and worked: objects brought up by a correct sequence of lifecycle steps, a shared environment, apps that are almost no code. Agents buried it under restored old code and new layers.
- The new version of gppu is good because of the way it works with the runtime and state. It needs no custom classes for things like state managers or groups: all of that is handled natively by runtime or by state. That is how apps work without code.

## Environment
- How many environments exist, and why they are initialized the way they are, is settled and has been explained several times.
- `environment=` on an app is invented and is the worst way to initialize the code. An app dealing with its environment violates the principle.
- The environment is global and purely a system object. It is created once and stays a global object, hidden from everybody: nothing downstream uses or touches it. gppu's own methods use it to do things correctly, such as building paths.
- There is no environment config file exposed to programs. A program reading the environment's file or folder (`Env.path.parent` in Y2) is the opposite of how it works.
- `Env` is part of gppu and always exists, so a program never works with it. `Path` just works: a program calls `Path` and opens the file, and never parses paths. The same goes for `Env`: the program uses the library.

## Runtime
- The lifecycle of an object is a feature of runtime.
- There are exactly two relations between an app, or an object, and its runtime. It is impossible to come up with another one, and both use cases are handled.
- The initialization steps are the way they are for reasons that are described.
- Applications do have a runtime. It has been scattered over various classes: in one place it is called app, in another async app or MQTT app, or a state manager. All of those are effectively the runtime, but it is Y2's runtime, as opposed to a generic and better working one.
- Runtime does not work at all at present, so nothing executes the lifecycle.
- There are events in runtime.
- In any list of dicts that objects are produced from, a row may carry `class`: exactly the name of the class of the object it initializes. The field is `class`, standardized from `kind`. A row without it gets the default class.
- A thing keeps its class even when it becomes as simple as a REST group that runs REST commands, as Hue can: its class may have nothing but its name. Classes are rarely added.
- Loading objects from a list is not inside the async app.
- When the runtime builds an object, it builds everything the object needs to have its actions.
- A restart never performs an action that nothing triggered. An action performed on restart means a problem in configuration or code.
- No action happens on a restart because nothing triggers one, not because actions are suppressed. Nothing is suppressed.
- A restart loses no state: there is no time after it when everything is unknown and no state appears. Everything works from the first second.
- An action or a loss of state on start or restart comes from incorrect initialization of objects. It is found by reading configuration and code, never by experimenting.
- Time of day is triggered by cron, not by Y2's TOD, where it is disabled.
- Polling is polling: it happens on an interval. Calls, callbacks, timeouts, poll interval, long poll and retry are universal: they say how poll commands are launched, on what schedule, at what interval and on what event. A Hue poll interval works no differently from any other poll interval.
- Polling may differ between runtimes. What a poll does differs from entity to entity; whatever does the polling cares only about the schedule, and polls on the right event.

## State
- State is the state. It is what the application preserves, and restores on restart. With a state, init and load do not have to be done all over again every time.
- It is done through persistence.
- State comes from talking to a device through its API, or from an event that arrives through a subscription.
- Events arrive from MQTT, and everything on MQTT is retained. An app may start with objects without state; once its subscriptions are enabled, within the first second, they receive the last known state of their devices.
- Devices without state whose state comes from polling are polled first. On start there is a queue of devices to poll, and the initial poll, for initial state, is much more aggressive than the regular poll, so they have state within the first several seconds.
- So an object without state is never seen.
- State is a DC, not a dict. That was lost on the way to simplifying App.
- Every app has a state. A state that is not persisted, or is bypassed, is still a state. Users of gppu have state: Y2, rewrite-commits, the utilities, Preservator, which knows when it last ran.
- The previous version of Y2 had an object called state that contained the state. Y2 may now be loaded from scratch every time and keep none.
- There are no events in state.
- What the state object does is give quick lookups: all the lookups around the state.
- There is a lot more to Y2's state than identity to entity.
- State plus runtime is a much better state machine than a separate one. All of the code is still there; it is not packaged correctly.

## Resolving objects
- State, runtime and the importance of resolving objects go together.
- Objects have given names: a path, a slug, or kebab case.
- An action is the example of an object with a globally unique name: knowing its path, an action can always be looked up.
- Entities are one use case in Y2, with the eid notation. Actions, paths, hosts in kebab case, and anything else with a globally unique name can be referenced in configuration by that name. All of it is resolved automatically into whatever it needs to resolve into when the code is run. That is why the code that runs a sequence is so short.
- One object talking to another is the less common use case. The more common one is something like an admin UI built on top of the objects in runtime.
- Every notable object has a stable, globally unique ID, so it can always be found: to get the state of a sensor, you know how to find it.
- The globally unique ID is what enabled state. State is possible because there is a globally unique ID.
- Complex configurations can be made very simple, because anything can be referred to by its globally unique, human-readable ID. That is why configs are so simple, especially for actions.

## Objects
- All objects are derived from DC, and so they do not need constructors.
- The REST mixin does not work and gets in the way: comment it out or declare it deprecated.
- A Tuya light entity and an Insteon light entity are the most basic example: two lights, different approach, same code. What differs between them, from the point of view of environment, runtime and state, in code and in configuration, shows the two relations between an object and its runtime.
- The difference between them is not templates and is not runtime. Hue against Insteon, Tuya or Kasa shows that.
- There are no pushed and no pulled objects. Pushing or pulling objects is a blatant violation.
- There is no such thing as a row.
- Insteon's device and Y2's device are the same. The difference between a device and an entity is superficial: name, members and entities. The AV device and time of day are to be looked at as well, not one device.
- A group has two lists that declare membership: members and entities.
- `members` contains references. `members` is not state. `entities` is not runtime and not environment.
- Deprecated, poorly implemented code is not evidence about the architecture.

## Topics
- A topic is MQTT. It can be subscribed to, not set. Code that sets a topic is to be eliminated; what breaks because it relied on that should be broken.

## Actions
- Action is the formal name. An action is globally unique.
- Actions are what give a UI: a UI cannot be built without actions, and no TUI would know what to do without them. Classes interact through actions.
- Code that avoids actions and hard-codes instead is not correct. Actions are the only way.
- Understanding how entity state works is not understanding actions.
- Layouts, scenes and events are all actions.
- Actions can be in a sequence, and a sequence of actions has a name.
- Actions are poorly defined today: actions and action paths are built in many places. Topics have the same problem: the topics power is published to are declared in many places, with no good way to centralize them.
- Objects are to register their actions, the paths that are uniquely theirs. That they do not register them is why it does not work.
- An object knows from its configuration the places it publishes its state to: a simple topic for just the value, and a full topic with the state of the object. None of those paths is registered anywhere, so two objects can post their state to the same topic, or two adjacent objects can build their state topics differently.
- Wanted: a check at run time that there is no collision, and a reverse lookup from a topic to the object that publishes it and whether that object is alive.

## Every way an app is launched
- A tool is not to have a separate CLI, a separate GUI and a separate UI, each repeating what it can do, nor a sidecar text file beside it repeating it again. All of them rely on actions and need no functionality of their own.
- PC Control's layouts and scenes are actions. PC Control should use actions and register them, not declare its own listener to a topic.
- Preservator's steps and its preset are a sequence of actions: not executed on an entity, but still a named sequence of actions. Preservator needs to know what can be preserved and what can run in parallel.
- Preservator is not a service, so it does not listen to MQTT; if it were, triggering the action there would run it. The TUI discovers which sequences are available and runs them. The same named sequence runs from the CLI, from an import as a library, from the TUI, and from a GUI, a web UI or a web service built for it. All of that comes from actions.
- Fleet management is a task of its own: nice and clean, with individual steps that are not polluted and are reusable. Each step is executable individually and is a very simple script. `mapper.cmd` is the example, five lines, and the Docker update another. A step stays that small and can still be launched in many scenarios: synchronously, asynchronously, by name.
- A utility that parses its own command line and arguments, separately uses gppu, and separately does something with YAML files is an error, and that file is flagged for a rewrite. The list of such files holds only code that is actually used.

## Configuration
- Defaults are in the template; a particular case overrides them. Some AV buttons on keypads are the example.
- The convention notes what is always implied and specifies the cases that need a special case. The number of special cases is tiny and is to stay tiny.
- In configuration done correctly there is not a single line that does not directly affect behavior, and not a single line repeated. The Insteon scenes are the example.
- Lists of objects that each repeat the same ten properties are the opposite, as is having to modify five configuration files to get one sensor to work, and still not knowing which topics it publishes to and what reacts to it.
- Configs stay light because the defaults are so powerful. Saying an object is `ao-desklamp` is enough: the name gives its path, what it is, what it does and how to talk to it.
- Slug and path used to be simple built-in properties of a data class and may no longer be well defined. The cases where a path and a slug cannot be used interchangeably are tiny in number, but they exist.
- There are enum-like objects in `_creekview.yaml`: a topology that gives the nesting and the synonyms, and a dictionary of tails and heads. They are needed to build paths correctly; with them the vocabulary is constrained and building a path is deterministic.
- `infer_area` is the old method that identifies an area from just the name of an entity.
- A conversion from domain to prefix is not used and not needed: it is declared differently. It is not a missing piece and is not to be required.
- Care is needed with the words name, path and system.
- A measure is attribute-only. It is the first use case not handled by the model: it works, but on the side. It is the first non-entity object, and it requires no decision.
- Configuration is explicit and authored by Alex, and carries the systems' own IDs beside his own information. gppu and Y2 assume it matches the live systems: they keep no copies of live configuration, generate none and discover nothing.
- Keeping those IDs in sync with the live systems is a prompt and a skill. Where configuration holds IDs that come from a live system, it carries a short prompt that says where they come from and points to the skill that brings them in sync.
- There is one object for each thing: one light in the configuration and in the system for each light.
- A light is configured the same way whatever drives it, Hue, Tuya, Insteon or any other: declaring a light, its behavior and its room is done for it as a light, so lights mix and match. Covers and groups work the same way.
- An entity is generic, built from configuration that produces its dictionary. It speaks a system because its dictionary carries that system's ID: a cover whose row has a PowerView ID speaks PowerView, and has every generic feature besides.
- PowerView's configuration is not generated: each cover's and each scene's PowerView ID is part of its declaration.
- Configuration defines the things that need commands executed and the things that know how to execute them.
- One kind of configuration describes how a system behaves: how it executes an action, by mapping the action to the system's API call, and how it calculates state. It is a mapping of a dictionary to a dictionary, and is almost code.
- A system whose API works differently between versions is still the same product, and needs no new object: the difference is in that system's configuration. PowerView's V1 and V2 hubs are the example.
- The other kind is the configuration Alex and users care about. It says this is the room, the room has these lights, and what happens when it is turned on and off. Those are sequences, and a sequence is a list of commands.
- The two kinds are never intermixed. What a system exposes, and Alex may rename, such as Hue's lights and groups, is in the users' kind, in the same file or another. How setting a Hue light red becomes a POST to the bridge is in the system's kind.
- The users' configuration is Creekview: it describes the whole house, what lights belong where. It is human-readable, has nothing excessive, and is meant for editing. It may be a very large file; nested well, it gives a view of everything, and it is not crowded with how requests are built from templates. Today it is groups. Its format is universal: everything is a group.
- Every entity a user may be expected to interact with, a named entity such as one exposed to Homebridge, can be in that one file: one big foldable topology, not polluted with the specifics of how Homebridge is built.
- Homebridge is configured in one place, `homebridge.yaml`: it holds everything needed to change how Homebridge works, and it is the only file to look at for Homebridge. Nothing of Homebridge is hard-coded in code.
- In `homebridge.yaml` the user only says which entities each Homebridge instance exposes. Homebridge picks the template that exposes each entity correctly; how that becomes Homebridge's configuration is a different scope.
- What is special about an entity, such as an overridden area, is the entity's metadata, not Homebridge's.
- Templates, generators of API requests and formatters are the technical part a user does not look into. Big templates, such as Homebridge's, can be external files.
- Nothing about how actions are performed is hard-coded in code. Everything about doing actions is in one kind of configuration, and the higher abstractions, such as groups, are in the other.
- What is specific to a device moves into configuration even when it has only one or two uses, such as the matrix's: the user never has to open source code, because there is nothing for him there. The source code works and never changes, and the system works as its configuration declares.
- Something stateless that has an ID and a direct API call, such as triggering a scene, is an action, not an entity: it needs no entity ID and no entity of its own, and it is never created as two actions.
- A cover group that exposes several covers as one cover is its members and its scenes. It is declared directly, with its scenes' IDs, without declaring the scenes.
- A scene or an action that can be triggered by a path has only one path, the user-friendly one.
- Triggering an action is stateless: no response comes back and no state change is looked at. It is much simpler than keeping the state of the action's participants, and the two can take different paths.
- An action is triggered the most direct way its system allows. For Insteon, whose PLM is connected to MQTT, that is MQTT itself, with no intermediate step such as publishing `action/ao/light/off`.
- Paths take the user's form: devices are conformed to how Alex wants paths to look, not his configuration to each device's peculiarities. Power is the example: a thing posts rich JSON to its own topic, and also posts to a common topic, where who posts is unknown but what is posted, such as temperature, is known, raw or formatted.
- Simple actions are not complicated with entities: an action can be triggered directly.
- An action never triggers another action. A sequence is a list of actions, and an action is a straight shot: never a generic light action that works out what to do, publishes to a topic, and has something transform and republish it.
- An entity with state is different: a change of its state is requested formally, through MQTT.
- ESPHome devices listen on their `btn/` topics and publish their `ind/` topics straight on the bus, not through Y2 or IoT. That approach is embraced, inside the code too.
- A service that talks to MQTT, such as zwave-js, Insteon's MQTT or Z2, is configured on its own side to speak Alex's path format natively: paths and sensor topics formatted exactly as he likes. Nothing republishes from one topic to another, as zwjs.py does today, so every path is uniform.
- For a given task the user never has to leave a single configuration file. Today the configuration is all over the place: Hue in more than one place, Kasa scattered, Homebridge impossible to take apart. Consolidating it by these rules makes the topology readable.

## Presses and indicators
- Incorrect triggering comes from code added to work around cases that the correct sequence of polls and callbacks would never produce. It is fixed by following that sequence and removing the workaround.
- A press of a keypad button triggers its action exactly once. A button in the device's hardware scene already sends the command over the wire, and Y2 sends none for it.
- An indicator shows its source: when the garage door sensor shows open, every button of its indicator is on. No button stays in the wrong position, because the system knows each button's state.
- An indicator's state is retained like any other state, and a mechanism keeps the state of every button of an indicator matching the indicator.
- A pressed button may be out of sync with the rest of its indicator for a few seconds: the action the press triggered takes time, and its feedback may come by a completely different path, such as power consumption. That is fine: the user pressed the button and sees it in the state he pressed it to.
- That is what the poll is for: a button that stays out of sync after that time is brought back to its indicator.
- Polling a device makes it re-report its most recent state, and that is all a poll does. There is no separate path for polling: the report triggers a state change, which triggers the indicator change like any other.
- There is one path to an indicator update: a state is reported and the indicator is updated. A report of an unchanged state, a device that stayed off, takes the same path, so polls several times a day bring indicators back even with no change. Nothing about an indicator change differs from a state change.
- All that is needed is callbacks and polls, trusted. Code that adds timeouts, retries, fallbacks and the like around them is a hack and is removed.
- No individual step is forced to succeed: no repeats, retries or fallbacks. Things are done gently, knowing that a step that failed, say in a broadcast storm, is picked up by a poll.
- A device is polled again soon after a command to it, as AV devices are 30 seconds after one. A device whose state change did not arrive in real time, or within a few seconds of it, is first in the queue to be polled again. Every device is polled at least once an hour.
- Keeping buttons matching their indicator is not about catching every case. After a press the keypad in front of the user is probably already right; what matters is that the entity's next refresh comes soon, in a queue. Flapping is not removed by manipulating how the system works: a longer delay is allowed, because a more thorough round follows.
- A command to an indicator is sent to every button of the indicator.
- A change of a source's state triggers a state refresh, and the refresh sends every notification due, one of them to the indicator. Whether a button needs a command is decided by that button's own state, not by the indicator's group state.

## UI
- All objects are data classes with the same `self.data`, and state is lists and dicts of them, so any object can be displayed in a list by a UI that knows nothing about it.
- A UI adds a layer: how to lay the elements out nicely for a given type of data class.
- A basic UI with full function needs no code. Default templates display objects in a list and in a grid, so any DC object is displayed, with its actions.
- UI hacks to work through: UI not using templates, using different templates, not looking at objects, or presentation completely separate from the object's state, so the object cannot be displayed.
- Well-designed objects have HTML that remains. The defect is the model being in many places at once.
- UI templates do not move into `gppu.py`; they play nicely together with it.

## The model breaks — decisions the structural rewrite needs (surfaced 2026-11-22, by the static reduction)
These are where the one-shot stopped because the architecture as stated did not yet say what to do. Each is answered from what Alex said: items 1 and 8–11 from the environment, items 2–7 from runtime, objects and actions.
1. **Env without `path`.** A program never reads the environment's file or folder. A folder a program writes to is named in configuration the way `Path` opens it, as Alex writes them (`trace_folder: /home/alex/IoT/_Creekview/generated`), and the program opens it with `Path`: Ecobee's and covers' generated folders are `Path(<configured value>)`.
2. **Choosing an object's class.** A row names its class in `class`, standardized from `kind`; a row without it gets the app's default class (`AsyncApp._default`).
3. **The two relations between an object and its runtime.** The runtime either refreshes the object or routes events to it. A Tuya light is refreshed: it has its own connection and is polled on its app's `poll_interval`. An Insteon light gets its events routed to it: its hub reports, and a listener passes the message on. `AsyncApp` already has both, its poller and its listeners.
4. **Timers: one Runtime's or each app's.** Each app's. Runtime is not a class, and an `AsyncApp` holds its own timers (`timers`, `h_timeouts`), which is what Y2's Supervisor counts.
5. **`mixin_Rest` removed.** It is not removed: it is declared deprecated, and it stays until Y2's UI and the admin UI serve their objects through actions, which are what give a UI.
6. **TUI as a mixin.** A `TUIApp` has no constructor. Textual's own `__init__` runs in the TUIApp's init step, after its data is set, as the last part of init. Today `TUIApp.__init__` calls `AsyncApp.__init__` and then Textual's, in that same order.
7. **The DB bases' constructors.** A database base is made from its data like every object. It takes `db` from configuration (the environment's, or its own) and connects on first use. Its users give it data as keywords, and its `__init__` overrides become its init step.
8. **Configuration that arrives after import.** It is the environment's: a host without the repository, as PC Control's, is given its sections over MQTT. gppu's own `AppService` puts a section into `Env` and fills it as the file is filled; `Env` has no load step to run again. Y2's `configure` gives `Env` the validator's candidate configuration the same way.
9. **The host.** A program reads the host to pick a location's local path on this machine (`locations[uid].access[host]`), which is building a path, and building paths is gppu's, through `Env`. Locations are gppu.fs's and the Lake's, out of scope for now, so `Env.host` stays until that work.
10. **Programs with their own file beside them.** They are Apps: an `App` takes its section of the environment, or the file or MANIFEST it is given, and gppu needs nothing more. `Env.from_env` does not exist, and nothing calls it.
11. **Relative paths in configuration.** `Path` is unchanged: a relative path is the current folder's, and an include is relative to the file that holds it. A folder in configuration is written so that `Path` opens it from anywhere (absolute, `~` or a variable), as in item 1.

## How the work is done
- The job of the supervising session: look at gppu, understand the changes that need to be made, then dispatch agents to make those changes.
- The base class structure and the module structure are the basic architectural work, done before any code is written. No session changes code without knowing the base classes and what is in which submodule.
- It is a refactoring job: use classes and mixins correctly, as the examples around show, and that way arrive at the base classes. Alex looks at the base classes and says go ahead.
- What goes in which module is trivial and does not need asking.
- All the changes are planned statically, by static analysis: write down the requirements, distill them to what is needed. Not by patching something and waiting for it to deploy.
- The process: look at the code, remove all unnecessary things, line it up, look at the code again. gppu is very simple functionality and is rewritten in one shot.
- The architecture is explained end to end; there is nothing left to design.
- No change to gppu requires SQLAlchemy.
- The one way to change gppu is one shot: look at code and configuration statically and reduce it to the absolute minimum, removing all functionality that is not needed or not used. Where the model breaks during the reduction, Alex is consulted. With classes and methods pruned, the architecture is obvious: what goes into which module and which class has only one answer. Then the code is moved into its submodule. gppu ends at a third of its size, with no tests: a designed system works when launched, it is not trial and error.
- One shot means it can be written with pen and paper, offline: it fits in one hand and a human writes it out in one go.
- The task cannot be executed by grepping code and reading documentation: that only adds complexity and never reaches the simplicity asked for.
- One session follows these instructions and writes code it understands, not patches and hacks to old code. It is a few classes. Most custom code leaves the peripheral programs.
- Every public method and every public function of every class is looked at and has to justify itself. Methods that should not be public stop being public; methods that should not exist are removed. Most of the code should not exist.
- The only messy code that remains in gppu is TColor, the colour printer: old and messy, and fine to stay.
- gppu's `Path` is the way to access files and work with paths, used everywhere uniformly. Reading from files has regressed to the version before `Path` handled path resolution.
- Understanding comes from analysing the running production code, not from markdown files of unknown origin. `SPEC.md` is not read.
- The conventions on topics and action paths are assembled in the vault, then simplified, then applied to all the users.

# What the agent found in the code

## Where the three objects are today
- Environment: `Env` in `gppu/gppu.py`, read with `glob`.
- Runtime, in pieces: `AsyncApp` in `gppu/app.py` (objects from configuration, loop, timers), Y2's `App` and `Runtime` in `y2/y2app.py` (listeners, registries of actions, buttons and indicators), `Y2.start` in `y2/__main__.py` (apps from `y2/apps`), `State` in `y2/y2entity.py` (loop, broker client), and each state manager.
- State: `State` in `y2/y2entity.py`, with entities starting as `newborn`. gppu's `_PersistentDC` (`gppu/data.py`) stores and loads a DC's data by class name and key; no app uses it. Apps that keep something across runs do it themselves: `RAN/Hosts/rewrite-commits/rewrite_commits.py:98-113`, Ecobee's token and Nest's session in Y2.

## Actions and topics
- Action paths are built in nine places; only Y2's action manager checks for a duplicate.
- Topics are registered nowhere.
- PC Control listens on its own topics (`devices/dc/set/scene`, `…/set/sleep`, `devices/dc/<host>/set/<command>`) and registers no action (`IoT/PCC/src/pc-control.py:152-154`, `246-257`, `301-337`). Y2 already has the layouts as actions over a PC entity's commands (`_Creekview/_devices/av.yaml:537-546`, `y2/av.py:334`).
- Preservator's steps are named in configuration, and `--cells` prints each host and step with its locks (`RAN/Hosts/preservator/preservator.py:12`, `317-336`). Its preset is held by the fleet grid (`RAN/Hosts/configure-all/fleet-tui.py:145-158`).
- 20 current tools carry a launcher `MANIFEST` in the file and 25 `manifest:` YAML files sit beside tools. `CRAP/Systems/craptui/preservator.yaml` lists six modes, each a list of flags of a script since archived. `RAN/Hosts/mapper.cmd` carries a `MANIFEST` after its five lines.
- A fleet step is declared in `RAN/_config/hosts/runbooks.yaml`: `tasks`, and `runbooks` as a name over a list of task names. Three programs run steps, each its own way: `configure-all.py`, `preservator.py`, and `fleet-tui.py`, which learns what the other two offer by running them and reading what they print. PC Control runs `mapper` a fourth way, as one of its own operations.

## Configuration
- A measure exists as the second segment of a value topic (`comfort/<measure>/…`, `sensor/<measure>/…`), as a key in `State.sensors`, and as an attribute of the entity that names it under `attributes:`. Which measures exist, their units and how they combine are each written in a different place.
- `areas`, `subareas`, `floors`, `floors_deep` and `infer_area` are in use. `indicator_tails`, `indicators`, `superareas`, `floors_simple` and the tag meanings were removed from `_creekview.yaml` on 2026-09-12.
- The conventions, what a name implies, the special cases and the places configuration repeats what is implied are in the vault at `_Standards/drafts/Conventions/Topics.md`.

## gppu.py: the architecture, step one (2026-11-22)
Read from `gppu.py` alone. Alex's code stays as it is; what changes is code agents wrote, at the places Alex marked.

The three objects:
- Environment: `Env`, made as gppu is imported, always there, hidden. It holds the environment's configuration, which `glob` reads, and what gppu needs to know of the machine: os, home, host, user, and where the environment's file is. gppu's own code uses it: `glob`, `App` taking its section, `Path` building a path. No program touches it.
- State: a DC; not in `gppu.py` yet, and its persistence is Alex's to add.
- Runtime: not a class. The lifecycle steps bring an object up; the loop is `AsyncApp`, in `gppu.app`.

The base classes:
- `_DC`: every object, built from its data in one go; its annotations are properties over its data; no constructor of its own.
- `_YMRO` → `YInit` → `YLoad` → `YStart`: the steps; each class adds its own private part of a step.
- `_mixin`: a capability. `mixin_Logger` is the one log; `mixin_Config` is the `my` readers over the object's data.
- `_Base(mixin_Logger, mixin_Config)`: the foundation.
- `App(YInit, _Base, _DC)`: an object with its own configuration: its section of the environment, or the file or MANIFEST it is given, under what it was made with, and the command line over both.

Everything else in `gppu.py` is access:
- Files and names: `Path` (a program calls it and opens the file; it expands a text path and reads text as UTF-8), `y2list`, `y2path`, `y2topic`, `y2uri`, `OSType` and `detect_os`, `probe_path` (approved as a hack).
- Values: `safe_int`, `safe_float`, `now_ts`, `format_size`, `pfy`, `slugify`, `uuid_create`, `TimeSpan`.
- Configuration: `deepget` and its typed readers, `deepset`, `dict_from_yml`, `dict_to_yml`, `YmlLoader`, `jinja` with `render_template`, `apply_template`, `jinja_template`, `jinja_fill`.
- Output: `TColor` and `pcp`, which stay as they are; `Logger` with `Debug`, `Info`, `Warn`, `Error`, `Dump`.

What changes, at Alex's marks, in agent code only:
- `Env` (marked Rewrite, and its load): a system object with no load step. It reads its file as it is made, and its Jinja is filled once `glob` reads it. What it knows of the machine (os, home, host, user) is plain attributes, not its data; those lines keep their marks.
- `mixin_Config` (marked): the `my` readers over the object's data, nothing more.
- `App` (marked Rewrote): follows the architecture, not beside it.
- The Jinja region (marked AI, not human reviewed), the largest block agents wrote in the file, has each method justify itself.
