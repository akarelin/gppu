# gppu 3.8

Alex's instructions are in [SPEC.md](SPEC.md). The earlier, longer version of this file is in git history (gppu 28232bb).

## Release
- [x] The status line released: statusline 0.7.6
- [x] gppu stays on 3.7.11: a build with no bump moves the 3.7.11 tag to master and builds it, and betas are off the menu (2716f70). `gppu/latest` and 3.7.11 are master, and `~/.venv` on alex-pc runs it: the Hosts TUI starts and draws its menu, and the TUI's, Preservator's and the Fleet grid's tests and PC Control's checks pass on it
- [x] `pip show gppu` shows the time of the build's commit after a `+` (`setup.py`), Alex as author and gppu's GitHub repository; a plain `pip install -r requirements.txt` takes each new build
- [x] The gppu wheel carries only the gppu package, and its source archive only the library and the files that build it; the next gppu build releases it

## gppu's code, by Alex's marks
- [ ] `Logger.enable_file_logging`: "Need justification for this to exist" (in progress)
  - What it does: RAN's `config.yaml` has the line `log_file: ~/.cache/gppu/hosts.log`, so every program that loads RAN's configuration also writes every line it prints into that one file. Creekview's configuration has no such line
  - The file's lines have no time, severity or caller. Preservator, the Hosts TUI, rewrite-commits and test runs all write into it. No program reads it
  - Logging is set up in six places: the top of `gppu.py` makes the console output; the `Logger` class, far below, gives it colours and a filter; loading the configuration applies `trace_rules` and `log_file`; `init_logger(name)` renames the log, a name nothing prints; every class gets its own log when it is defined; the TUI launcher swaps the console output for its own panel while it runs
  - The CRAP file indexer, Plaud and Transcriber scripts and RAN's md-indexer import `init_logger` from `gppu`, which no longer offers it, so they stop at import
- [ ] `mixin_Config`: "It DOES not read the configuration ... self.my was initialized somewhere and needs a place, but not this complexity"
- [ ] `App`: "Not human reviewed" and "Rewrote. folowing the architecture, not beside it"; an app declares RAN or IoT, which decides Env's environment, so a built app such as PC Control has its environment
- [ ] The Jinja region: "AI, not human reviewed"
- [ ] The old tracing block, commented out, with "Ignoring all python3 libraries"
- [ ] `gppu/app.py`, once its edits are committed: `TimerHandle` ("Unjustified class"), `_Scheduler` ("Antipatterns"), `_Runtime` ("This is not runtime. It is bad code from y2"), `state_changed` ("This is state, not runtime"), `listen_topic_state` ("Topics do not have states")

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
