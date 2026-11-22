# gppu 3.8

Alex's instructions are in [SPEC.md](SPEC.md). The earlier, longer version of this file is in git history (gppu 28232bb).

## Release
- [x] The status line released: statusline 0.7.6
- [x] gppu stays on 3.7.11: a build with no bump moves the 3.7.11 tag to master and builds it, and betas are off the menu (2716f70). `gppu/latest` and 3.7.11 are master, and `~/.venv` on alex-pc runs it: the Hosts TUI starts and draws its menu, and the TUI's, Preservator's and the Fleet grid's tests and PC Control's checks pass on it
- [x] `pip show gppu` shows the time of the build's commit after a `+` (`setup.py`), Alex as author and gppu's GitHub repository; a plain `pip install -r requirements.txt` takes each new build
- [ ] The gppu wheel carries the `statusline` and `w11` packages, and its source archive every file in the repository

## gppu's code, by Alex's marks
- [ ] `Logger.enable_file_logging`: "Need justification for this to exist" (in progress)
  - What it does: RAN's `config.yaml` has the line `log_file: ~/.cache/gppu/hosts.log`, so every program that loads RAN's configuration also writes every line it prints into that one file. Creekview's configuration has no such line
  - The file's lines have no time, severity or caller. Preservator, the Hosts TUI, rewrite-commits and test runs all write into it. No program reads it
  - Logging is set up in six places: the top of `gppu.py` makes the console output; the `Logger` class, far below, gives it colours and a filter; loading the configuration applies `trace_rules` and `log_file`; `init_logger(name)` renames the log, a name nothing prints; every class gets its own log when it is defined; the TUI launcher swaps the console output for its own panel while it runs
  - The CRAP file indexer, Plaud and Transcriber scripts and RAN's md-indexer import `init_logger` from `gppu`, which no longer offers it, so they stop at import
- [ ] `mixin_Config`: "It DOES not read the configuration ... self.my was initialized somewhere and needs a place, but not this complexity"
- [ ] `App`: "Not human reviewed"
- [ ] The Jinja region: "AI, not human reviewed"

## Independent, unscoped
- Objects read their configuration as `self.name`
- Hosts: one lookup in RAN and Creekview
- Configuration from MQTT in one place
- One mechanism for hosting and spawning processes
- Container apps, and MQTT status and last will for free
- Connection strings as one-line values
- UIs on gppu's Jinja

## Found outside this task
- Programs still call `Env.from_env`, gone since 3.7.1, and stop at start: in RAN the Linked Data API and its tools, lake's m365, md-indexer, eMail-triage, coverage; in CRAP the admin UI, Transcriber, the file indexer, Plaud
- The Hosts TUI's Configs browser reads `configs_config`, which RAN's configuration no longer has
- The start page has no `start_page` configuration in RAN since 2026-11-13, and imports the sidecar loader gppu no longer has
- IoT: `_creekview.yaml` and `ui/editor.yaml` include `zwjs.yaml` and `z2.yaml` from `Insteon/`, which Alex moved back to `_devices/`; Creekview does not load from the checkout
- IoT's any2mqtt image is `python:3.13-slim` and installs `gppu/latest`, which imports `uuid7` from Python 3.14

## Y2 (the gppu-3.8.0 session)
- Y2's objects load natively by `_DC`, with no constructors of their own
- Y2's State is gppu's
- Y2's entity is part of gppu
- y2 rebuilt on the release and deployed
