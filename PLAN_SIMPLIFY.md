# gppu 3.8

Alex's instructions are in [SPEC.md](SPEC.md). The earlier, longer version of this file is in git history (gppu 28232bb).

## Release
- [x] The status line released: statusline 0.7.6
- [x] gppu released from master by its GitHub Action: 3.7.11; alex-pc's `~/.venv` runs it from `gppu/latest`
- [x] On that release on alex-pc: the Hosts TUI and its utilities, Preservator and the Fleet grid, PC Control's checks

## gppu's code, by Alex's marks
- [ ] `Logger.enable_file_logging`: "Need justification for this to exist" (in progress)
  - It writes the log to the file an environment's `log_file` names. RAN's `config.yaml` names `~/.cache/gppu/hosts.log`; Creekview names none. `Env.init` is its only caller, and `Logger.file_log`, which RAN's rewrite-commits calls, writes to the files it opened
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

## Y2 (the gppu-3.8.0 session)
- Y2's objects load natively by `_DC`, with no constructors of their own
- Y2's State is gppu's
- Y2's entity is part of gppu
- y2 rebuilt on the release and deployed
