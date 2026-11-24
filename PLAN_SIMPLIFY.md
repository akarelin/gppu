# gppu 3.8

Alex's instructions are in [SPEC.md](SPEC.md). The earlier, longer version of this file is in git history (gppu 28232bb).

## Release
- [x] The status line released: statusline 0.7.6
- [x] gppu stays on 3.7.11: a build with no bump moves the 3.7.11 tag to master and builds it, and betas are off the menu (2716f70). `gppu/latest` and 3.7.11 are master as it was then; `~/.venv` on alex-pc imports gppu from the `D:\Dev\gppu` checkout, so the programs it runs take every change to master at once
- [x] `pip show gppu` shows the time of the build's commit after a `+` (`setup.py`), Alex as author and gppu's GitHub repository; a plain `pip install -r requirements.txt` takes each new build
- [x] The gppu wheel carries only the gppu package, and its source archive only the library and the files that build it; the next gppu build releases it
- [ ] PC Control imports `MqttApp` and calls `submit` and `call`, which master no longer has (`schedule` does both): a build of master stops it at import until it moves to an async app's MQTT and `schedule`, at the release that takes it

## Step 1: gppu reduced statically (in progress)
- [x] Logging is one `Logger`: the console, its colours and filter, and the trace rules; `init_logger` is gone
- [ ] File logging: RAN's `log_file` was commented out when the file handler was removed on 11-21; judged against Alex's words, it comes back as one line or is shown to be a hack
- [x] Logging is as it was in March: `Debug`, `Info`, `Warn` and `Error` call the log, and `mixin_Logger` gives a class a log under its own name; the caller's frame is no longer read
- [x] Device controls run on their app's loop; `SerializedControl`'s own loop thread and `_control_submit` are gone
- [x] `Env.reset()` as Alex wrote it
- [ ] AsyncApp's lifecycle is async; today it runs the sync steps, and an `async def` step part runs through `@sync` without being awaited (waits on Alex)
- [x] Timers are `mixin_Timers`, `run_later` and `run_every`, separate from AsyncApp's loop and lifecycle; `mixin_Groups` refreshes its objects through it
- [x] An app's objects, the rows at its `key`, are `mixin_Groups`', not AsyncApp's; `poll()` is gone
- [ ] MQTT is initialized the same way as the other objects (waits on Alex's words: its connection is neither a field nor read in a step of its own)
- [ ] Y2's State is a lookup of entities, not an app made at import that is Y2's MQTT client with its own publish and listen (waits on Alex: which app holds the MQTT connection)
- [ ] Device classes build on their base classes, each keeping only its device's own calls (in progress: every device file checked against the bases)
  - [x] PowerView speaks its hub's API in covers.py: a group's command is its scene and its double press the vanes; a shade reports the position its hub reads and is not moved on its own; a device starts and stops its entities in YDevice
  - [x] Sensibo: no has_actions, host field, own repr or remembered unit
  - [ ] Sensibo reads a `read:` field no Creekview row has, and its pods sit under `climate`, which no app's key reaches; one AO AC row (waits on Alex: configuration)
  - [ ] Hue under ten lines
  - [ ] Kasa: a strip built and connected as AVMatrix connects, its outlets' commands through the base
  - [ ] Kasa reads its settings as its own fields, from its own section (code ready; waits on Creekview's top-level `kasa` section)
- [ ] Y2's `y2entity.py`, by Alex's marks, read and fixed in this order (in progress)
  - [x] One `command`: the entity's own method, then the row's calls or a group's members, then its MQTT payload; `entity_command`, `has_actions`, `_sequenced`, `incorrect_first` and YEntity's and YGroup's `command` are gone
  - [ ] `commands` and the color loop's `command` go; `command` is async
  - [x] A press on `btn/<path>` reaches the entity at the path; the Buttons app is gone
  - [ ] `Runtime.buttons` goes
  - [x] An entity holds no listener handles of its own (`_listen`), does not unregister itself, has no `listen_state` and does not listen to its own state topic
  - [ ] No state saved to YAML and no hand tracing of calls
  - [ ] Runtime is State's: `state_changed`, the listeners and the registries; App keeps no state of its own
  - [ ] Unapproved global functions go into the class that uses them or go: `motion_topic`, `base_object`, `answers_actions`, `object_from_base`, `from_name`, `host_addr`, `runs_colour`
  - [ ] Z2Light goes: a zigbee2mqtt bulb is a YEntity
  - [ ] YRoom's own `_compute_state` and `ignores_nightlight`, YDevice's `host_addr`, GSM's `construct` and `_helpers`, mixin_Occupancy's `_occ_cfg`, mixin_Attributes' hard-coded attributes
  - [ ] A blinds group's double press sets the vanes through its row's `actions:`, which the cover_group template would carry (waits on Alex: configuration)
  - [x] Device files keep no `__repr__` of their own; ZwjsSensor and HostEntity are `pass`; a row's `uid` is its own
  - [x] Sensibo's and Tuya's refresh read the device and hand the reading to the base, with no catch
  - [x] Nest posts its rooms' motion flavors through the base's `motion_posts`
  - [ ] Hue, Tuya, Kasa, Z-Wave, Flume, UniFi, Nest and AV: each app's section and poll from the base, the device's id as its `uid`
  - [x] Rows name their class in `class`, and Creekview writes it
  - [ ] Buttons and actions take one pathway: an entity registers its actions and subscribes its button in one loop; `_cb_press`, AM's button branch and `Runtime.buttons` go (ready in y2's working tree; waits on Alex: one owner in Creekview for each of the 21 buttons two objects share)
  - [ ] One async command, the core's, reaches an HTTP device as configured; Hue's and PowerView's own commands go (waits on Alex: the name of the device's own call, where its request is configured, a group's one request or its members', and how async reaches the device)
  - [ ] PowerViewHub builds no shades and groups from lists of its own (waits on Alex: how a YDevice is given its entities)
- [x] HomeKit is the homebridge compiler's: the entity base, rooms, blind groups and Sensibo no longer build Homebridge accessories
- [ ] `has_actions` goes: it hides that a device and its group share one name, and so one action topic and one keypad LED (the AO AC pod and the AO AC group; a Tuya light and its group; a shade and its group), and that keypad buttons and LEDs are built as entities that answer presses (waits on Alex: the names are configuration)
- [ ] Alex's `# !!!` marks: `App` (its loading is back in its one init step), `Env` (done but for how the environment is chosen, below)
- [ ] Y2's apps read their configuration as fields, not copied from a section by hand: Kasa, UniFi, Z-Wave, Flume, Nest, Insteon (Kasa waits on Alex: its settings are at `power/kasa`, and no `kasa` section exists)
- [x] `mixin_Config` is the readers, `my`, `my_int` and `my_float`, and no loader; `my_list` and `my_dict` go with their callers (Y2's mqtt2pg still calls `my_list`)
- [ ] `App`: an app is not made by passing it its own name. Its name is its class's, and given no configuration it reads the section named as it is (Preservator); App still takes a name passed to it, and the lake's and the Linked Data API's servers pass one
- [x] The Jinja region: each public method has a user (`render_template`, `apply_template` and `jinja_template` in programs, `configuration` in Env and App, `jinja_fill` in the catalog)
- [x] The old tracing block and `gppu/app.py`'s `TimerHandle`, `_Scheduler`, `_Runtime`, `state_changed` and `listen_topic_state` are gone
- [x] `gppu` and `gppu.tui` export only what programs import from them; the rest stays in its module, unexported
- [x] The cache fetchers and the heatmap, which no program imported, are archived; helpers only their own module calls are private
- [x] gppu.tui's tree browser and its adapters, the input dialog, the classified progress strip and the spinner and ANSI glyph sets, which no program used, are archived
- [x] The file-system probe is in gppu.fs.handlers, its one user
- [x] What the reduction removed since 3.7.9 is in `archive/`, beside the module it came from
- [x] A `TUIApp` has no constructor: Textual's construction is the last part of its init step (architecture notes, item 6)
- [ ] The database bases made from their data, with an init step and a connection on first use (architecture notes, item 7)
  - Waits on which programs use gppu today: a base made from its data needs each live subclass to give it data and move its constructor into an init step
- [x] gppufs (`gppu.fs` with `gppu.ld`) is a submodule of gppu, reduced as the rest
- [ ] gppu reduced to what the programs that use it today need (waits on Alex's list of them)
  - Read from the deployments: Y2 and its UI, any2mqtt's utilities, PC Control, Plaud, MCP United, the Lake and the Session Manager through Dagster with the admin UI's shared code it mounts, the Hosts tools, gppu's W11 tools, status line and examples
  - None of those reaches `gppu.ld`, `gppu.ld.sessions`, `gppu.fs.files` or `gppu.chrome`: the Linked Data API uses the first three, Transcriber's annotation scripts the last
  - The Linked Data API runs on five as stack linked-data, which trix's nginx serves at api.karel.in/ld/ since 10-22
  - gppu's examples use the TUI pieces and `gppu.fs.vfs`
- [x] gppu's tests run on the environment gppu has and pass whole; those of removed behaviour are archived
- [x] MQTT 5 on gppu's own MQTT: a listener knows whether a message is retained and when it was sent, and each listener gets a topic's retained state, however many listeners came before it (architecture notes, State)
- [x] The poller: no startup delay, each object refreshed at least once an hour
- [ ] A device is refreshed again soon after a command to it, and one whose change did not arrive is first (architecture notes, State); `poll(obj, delay)` did it and had no caller
- [x] `poll_delay` is gone from AsyncApp: there is no startup delay, and Y2's UI no longer shows it
- [x] MQTT connects with Creekview's `mqtt` as it is: the client takes the connection, the block's other keys are the app's, and the will and online status come only where a `status_topic` is named
- [x] A row names its class in `class`, exactly, among the app's default class and its subclasses; a row without it gets the default class (architecture notes, the model breaks, item 2)
- [x] Env is gppu's global system object, loaded as gppu is imported, with no init or load step and no `environment=` on any app; the machine is its class attributes
- [ ] Env: how RAN or Creekview is chosen. The line under Alex's mark still picks it from the script's path; his words say only that the environment determines the app, never the reverse
- [ ] Env without `path` (the model breaks, item 1): Y2's UI (`y2/ui/creekview.py`) and RAN's y2-compare skill script still read it

## Independent, unscoped
- Objects read their configuration as `self.name`
- Hosts: one lookup in RAN and Creekview
- Configuration from MQTT in one place
- One mechanism for hosting and spawning processes
- Container apps, and MQTT status and last will for free
- Connection strings as one-line values
- UIs on gppu's Jinja

## Found outside this task
- Programs that loaded their own file through `Env.from_env`, gone since 3.7.1 (in progress)
  - [x] Read their section of the environment, or the file they are given: the Linked Data API and its tools, YuE2, coverage, eMail-triage, openapi_query, qdrant, the admin UI, the file indexer (`file_indexer`, its stores' `db` from it), neo-mqtt's rule generator and bridge
  - [x] The lake holds the configuration it keeps in Everything and reads it through its own `section()`; the admin UI reads the lake's sections the same way
  - [ ] Transcriber's recordings tool and lake's m365 read a `lake.yaml` that exists only in archives
  - [ ] Plaud's hourly sync on seven, its sign-in and its TUI call `Env.from_env`; Plaud is not ported
- RAN's gppu skill names `MarkerProgress` and `spinner_frames`, which gppu.tui no longer has
- gppu's handler-ls example reads its catalog at `D:/TextLake/.catalog`, which holds no folder for alex-pc, so it stops there
- Y2's tests and the Hosts tests set up with `Env.reset()` and `Env.init(environment=...)`, which Env does not have; IoT's scheduler and layout test no longer call it
- The Hosts TUI's Configs browser reads `configs_config`, which RAN's configuration no longer has
- The start page reads a `start_page` configuration that was archived and its include commented out on 2026-09-29, and imports the sidecar loader gppu no longer has
- IoT: `_creekview.yaml` and `ui/editor.yaml` include `zwjs.yaml` and `z2.yaml` from `Insteon/`, which Alex moved back to `_devices/`; Creekview does not load from the checkout
- IoT's any2mqtt image is `python:3.13-slim` and installs `gppu/latest`, which imports `uuid7` from Python 3.14

## Y2 (the gppu-3.8.0 session)
- Y2's objects load natively by `_DC`, with no constructors of their own
- Y2's State is gppu's
- Y2's entity is part of gppu
- y2 rebuilt on the release and deployed
