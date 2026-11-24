# gppu 3.8

Alex's instructions are in [SPEC.md](SPEC.md). The earlier, longer version of this file is in git history (gppu 28232bb).

## Release
- [x] The status line released: statusline 0.7.6
- [x] gppu stays on 3.7.11: a build with no bump moves the 3.7.11 tag to master and builds it, and betas are off the menu (2716f70). `gppu/latest` and 3.7.11 are master as it was then; `~/.venv` on alex-pc imports gppu from the `D:\Dev\gppu` checkout, so the programs it runs take every change to master at once
- [x] `pip show gppu` shows the time of the build's commit after a `+` (`setup.py`), Alex as author and gppu's GitHub repository; a plain `pip install -r requirements.txt` takes each new build
- [x] The gppu wheel carries only the gppu package, and its source archive only the library and the files that build it; the next gppu build releases it
- [ ] PC Control imports `MqttApp` and calls `submit` and `call`, which master no longer has (`schedule` does both): a build of master stops it at import until it moves to an async app's MQTT and `schedule`, at the release that takes it

## Step 1: gppu reduced statically (in progress)
- [x] Logging is one `Logger`: the console, its colours and filter, and the trace rules; the file logging and `init_logger` are gone
- [x] Logging is as it was in March: `Debug`, `Info`, `Warn` and `Error` call the log, and `mixin_Logger` gives a class a log under its own name; the caller's frame is no longer read
- [x] Device controls run on their app's loop; `SerializedControl`'s own loop thread and `_control_submit` are gone
- [x] MQTT reads its connection, the configuration's `mqtt`, in its init step
- [x] `Env.reset()` as Alex wrote it: `Env.init()` after it reads the configuration again
- [x] AsyncApp runs an app on its loop through its lifecycle (init, load, start, stop); its timers, a separate thing, are `run_later` and `run_every`. An app's objects, the rows at its `key`, are `mixin_Groups`'; each object is refreshed by a `run_every`, and `poll()` is gone
- [x] MQTT's connection is its `mqtt` field, read where it connects
- [ ] Alex's `# !!!` marks: `App`, `Env` (Env waits on Alex: programs declare their environment, about 175 files)
- [ ] Y2's apps read their configuration as fields, not copied from a section by hand: Kasa, UniFi, Z-Wave, Flume, Nest, Insteon (Kasa waits on Alex: its settings are at `power/kasa`, and no `kasa` section exists)
- [x] `mixin_Config` is the four readers over the object's data, `my`, `my_int`, `my_list` and `my_dict`, each read by programs
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
- [x] The poller: no startup delay, each object polled by its own next poll time, at least once an hour, and `poll(obj, delay)` puts a device first or soon when its state, an event or a command calls for it (architecture notes, State and Presses and indicators)
- [x] `poll_delay` is gone from AsyncApp: there is no startup delay, and Y2's UI no longer shows it
- [x] MQTT connects with Creekview's `mqtt` as it is: the client takes the connection, the block's other keys are the app's, and the will and online status come only where a `status_topic` is named
- [x] A row names its class in `class`, exactly, among the app's default class and its subclasses; a row without it gets the default class (architecture notes, the model breaks, item 2)
- [ ] Env, rewritten as marked: an app declares RAN or IoT and the rest follows from it; today Env, made as gppu is imported, guesses the environment from the script's path (waits on Alex: the model breaks where the declaration comes after the import)
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
- Y2's tests and the Hosts tests set up with `Env.reset()` and `Env.init(environment=...)`, which Env no longer has
- The Hosts TUI's Configs browser reads `configs_config`, which RAN's configuration no longer has
- The start page reads a `start_page` configuration that was archived and its include commented out on 2026-09-29, and imports the sidecar loader gppu no longer has
- IoT: `_creekview.yaml` and `ui/editor.yaml` include `zwjs.yaml` and `z2.yaml` from `Insteon/`, which Alex moved back to `_devices/`; Creekview does not load from the checkout
- IoT's any2mqtt image is `python:3.13-slim` and installs `gppu/latest`, which imports `uuid7` from Python 3.14

## Y2 (the gppu-3.8.0 session)
- Y2's objects load natively by `_DC`, with no constructors of their own
- Y2's State is gppu's
- Y2's entity is part of gppu
- y2 rebuilt on the release and deployed
