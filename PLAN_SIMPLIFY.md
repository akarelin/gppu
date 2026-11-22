# gppu 3.8

Alex's instructions are in [SPEC.md](SPEC.md). The earlier, longer version of this file is in git history (gppu 28232bb).

## Release
- [x] The status line released: statusline 0.7.6
- [x] gppu stays on 3.7.11: a build with no bump moves the 3.7.11 tag to master and builds it, and betas are off the menu (2716f70). `gppu/latest` and 3.7.11 are master, and `~/.venv` on alex-pc runs it: the Hosts TUI starts and draws its menu, and the TUI's, Preservator's and the Fleet grid's tests and PC Control's checks pass on it
- [x] `pip show gppu` shows the time of the build's commit after a `+` (`setup.py`), Alex as author and gppu's GitHub repository; a plain `pip install -r requirements.txt` takes each new build
- [x] The gppu wheel carries only the gppu package, and its source archive only the library and the files that build it; the next gppu build releases it

## Step 1: gppu reduced statically (in progress)
- [x] Logging is one `Logger`: the console, its colours and filter, and the trace rules; the file logging and `init_logger` are gone
- [x] `mixin_Config` is the four readers over the object's data, `my`, `my_int`, `my_list` and `my_dict`, each read by programs
- [ ] `App`: an app is not made by passing it its own name; how a program's app finds its section without one is open
- [x] The Jinja region: each public method has a user (`render_template`, `apply_template` and `jinja_template` in programs, `configuration` in Env and App, `jinja_fill` in the catalog)
- [x] The old tracing block and `gppu/app.py`'s `TimerHandle`, `_Scheduler`, `_Runtime`, `state_changed` and `listen_topic_state` are gone
- [x] `gppu` and `gppu.tui` export only what programs import from them; the rest stays in its module, unexported
- [x] The cache fetchers and the heatmap, which no program imported, are gone; helpers only their own module calls are private
- [x] A `TUIApp` has no constructor: Textual's construction is the last part of its init step (architecture notes, item 6)
- [ ] The database bases made from their data, with an init step and a connection on first use (architecture notes, item 7)
- [ ] Whether gppufs (`gppu.fs` with `gppu.ld`) stays inside gppu: the decision that sets gppu's size

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
  - [x] Read their section of the environment, or the file they are given: the Linked Data API and its tools, YuE2, coverage, eMail-triage, ticktick-export, openapi_query, qdrant, the admin UI, the file indexer (`file_indexer`, its stores' `db` from it), neo-mqtt's rule generator and bridge
  - [x] The lake holds the configuration it keeps in Everything and reads it through its own `section()`; the admin UI reads the lake's sections the same way
  - [ ] Transcriber, Plaud, md-indexer, iot-monitor: their files move into RAN's `_config` once Alex approves the move table
  - [ ] CCTV-detective and crop_possum2: their environment, and their table of moves
  - [ ] Transcriber's recordings tool and lake's m365 read a `lake.yaml` that exists only in archives
- The Hosts TUI's Configs browser reads `configs_config`, which RAN's configuration no longer has
- The start page reads a `start_page` configuration that was archived and its include commented out on 2026-09-29, and imports the sidecar loader gppu no longer has
- IoT: `_creekview.yaml` and `ui/editor.yaml` include `zwjs.yaml` and `z2.yaml` from `Insteon/`, which Alex moved back to `_devices/`; Creekview does not load from the checkout
- IoT's any2mqtt image is `python:3.13-slim` and installs `gppu/latest`, which imports `uuid7` from Python 3.14

## Y2 (the gppu-3.8.0 session)
- Y2's objects load natively by `_DC`, with no constructors of their own
- Y2's State is gppu's
- Y2's entity is part of gppu
- y2 rebuilt on the release and deployed
