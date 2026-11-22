# gppu simplification

Goal: gppu provides Env, State and Runtime, so Y2 only creates apps that share one State and one Env. Env is the global singleton app; it loads like any app and never initializes from itself. Alex's instructions are in [SPEC.md](SPEC.md).

## Construction and configuration (2026-11-21, in progress)
Principles: no new verb or noun; gppu.py core shrinks; downstreams that never used gppu right shrink most; every feature rests on SPEC, not on a caller. Baselines, dumps and the checks' output are in `D:\Work\11\21\gppu-construction`.
- [x] gppu master imports and its suite collects; baselines recorded for gppu, y2, IoT's TOD test and RAN/Hosts against this checkout and against 3.7.9: gppu 815 passed and none failing, where 3 failed and 12 files did not collect
- [x] One YAML parsing process in gppu's core: AppService's MQTT payload, a sidecar's manifest, the config editor's validation and a script's manifest parse with `YmlLoader`, and `dict_from_yml` reads YAML only. gppufs's parses wait with gppufs
- [x] A script's manifest is the YAML assigned to `MANIFEST` in its first 4 KB, taken by a regex in the one place where App loads a path: an app gives itself, `App(config=__file__)`, and the launcher loads each item through App. The launcher's parser for `.py`, `.cmd` and `.ps1` is gone (`test_inline_config`)
- [x] Configuration is the `_DC`'s data and `_my` is gone: `mixin_Config` is the readers and `_Base` the assembly; App adds the one step that loads; Env is an App whose data is the environment, and takes `config=` as an app does. Creekview and RAN load identically before and after, and identically on 3.7.9
- [x] `Env.init` is the two hard-coded environment paths and the load
- [x] Objects load as Y2's YData and YMRO did (y2 `bd717a3:y2core.py`): `_DC.__init__` is final, takes the row as its data and runs `init`; every class's private `__init`, `__load`, `__start` or `__stop` runs once, base first. `_INIT_STEPS`, `_init_from_kw` and `_init_config` are gone; App's loading and AsyncApp's own setup are their private `__init` steps, and the lifecycle classes are in `gppu.py`, where App is. Two classes of one name, gppu's App and Y2's, each keep their step. No class has a `__refresh` or `__publish` step, so the steps stay init, load, start and stop
- [x] Every app takes the command line: App reads `sys.argv[1:]` when it is given no `argv`; gppu's and y2's tests give their apps none through one conftest fixture each
- [x] The load-time template pieces, measured on the loaded configurations (`load_pieces.py`): the Jinja that reads only `glob` fills 9 values in RAN (`server_mounts`, four hosts' `mounts`, four OTEL endpoints) and 2 in Creekview (`groups/ao/2`'s `listen_topic` and `command_topic`); a row's `template:` gives 2699 values in Creekview and 84 in RAN, the 16 host rows; `jinja_configuration` registers Creekview's `macros` and 8 `*_templates` blocks for Y2's rendering and nothing in RAN. Each piece has a live use, so none is cut
- [x] The Jinja region's functions are methods of gppu's Jinja environment under their present names; the exported names are bound to the one environment, as `glob` is to Env
- [x] `Logger.enable_file_logging` is the one form Env calls, and says in place why it exists
- [x] Y2 on this gppu: it gives Env a whole configuration through Env's init, its tests reset Env before they load Creekview, and it no longer sets `Env.app_path`. Its dry runtime is identical (776 entities, 1812 actions, 18 buttons, 121 indicators), and its suite passes in one process as it does file by file: 480 passed, the 2 known failures, where one process failed 139 and errored 115
- [x] RAN's `hosts` hold every row whole: a row names `template: ssh` and loading lays `ssh` under it, so `glob('hosts')` is what Fleet merged, identical on 3.7.9 and on master, and Fleet reads it with no merge of its own (RAN 7b038bc66). A row's platform is still `Fleet.platform(row)`, its tag that names an operating system
- [x] Runtime, with its ListenerHandle, is in `gppu.app`, and so is the StateManager loader: `key` names a path into the configuration, each row there, of a list or of a dict by name, becomes `cls(data=row, parent=self)` by its `kind`, and its start step starts them (`test_the_loader_creates_the_objects_at_a_path_and_starts_them`). An app a loader made takes its row alone and loads no section by its name (gppu 6e860b2)
- [ ] Y2's objects load through the state manager's key loader, natively by `_DC`, with no constructor of their own
  - Today they cannot: an entity given its row by `_DC`'s init alone holds its data and does not start (`native_load.py`: `'YGroup' object has no attribute '_eid'`). 14 classes initialize in `__init__` (YBasicEntity, YEntity, YGroup, YRoom, mixin_ColorLoop, HueScene, PowerViewHub, TuyaLight, SensiboAC, Insteon's IIndicator, IEntity and IDevice, and Y2's App and State), and 7 state managers loop over their own sections in place of the key loader (Hue, Z-Wave, Flume, ecobee, Nest, hosts, Insteon)
  - Y2's `DataObject` keeps a constructor of its own with its list of steps, in place of the list gppu no longer has, until its classes' constructors are steps
  - Next: each constructor's body becomes its class's `__init` step, checked against the dry runtime dump

Independent and unscoped:
- Y2's state managers read their rows through `_DC` accessors, with no `_key`, `poll_interval` or section copies
- Swallowed exceptions in AI code. Gone: `Cache.get`, `set` and `delete` (gppu dad6355) and the close of ecobee's, nest's and UniFi's cloud session (y2 11d77db). Left: `HTTPControl` and `JSONHTTPControl` answering None for a failed request, which Y2's PowerView, Hue and AV callers branch on, so gppu and those callers change together
- Y2 onto gppu's loader: Y2's StateManager a thin subclass, its apps the rows of `y2/apps`, its `initialize`, `terminate`, `start` and `stop` overrides private steps, its mixins lifecycle members; `D:\Work\11\21\y2-gppu-overlap\review.md` lists every place
- Fleet in gppu under its own name, RAN's reduced to `expand` and `values`; a row's platform read from the environment
- Objects read `self.name`, their annotated accessors, never `my('name')`
- Y2's apps are the rows of `y2/apps` that Y2's loader creates, `cls(data=row)`; Y2's App stops passing `config=`. gppu's App would then load the section named as the app, and Creekview's `hue`, `av` and other sections carry the apps' names and a `name` key of their own
- Creekview's `ui/ui.yaml` loses its inner `ui:` level, so `y2/ui/data.py` reads its own data: with y2's next release, because the y2 running in the house reads `ui/ui` from the IoT checkout it syncs
- Creekview and RAN repeats, by named templates and the loader's key and parameters, not loops
- Error handling around logging goes: `dict_to_yml`'s and `dict_to_json`'s error files, which `Logger.Dump` reaches
- One MQTT connection: MqttApp's own `connection` key, and Creekview's seven repeated `connection:` blocks

## Env
- [x] App declares `environment='Hosts'` or `environment='IoT'`; `Env.init` selects the corresponding YAML file under `D:\Dev` on Windows and the home folder elsewhere. Basic runs with Hosts
- [x] App construction calls `Env.init(environment=...)`: it sets `host`, `os`, `user` and `home`, loads the declared environment once and applies its `log_file` and `trace_rules`; later apps share it until `Env.reset()`. An unknown name or a missing file raises. `Env.load` and `Env.resolve_path` are commented out
- [x] `examples/basic.py` uses Hosts, with Info and Debug output controlled by Hosts' logging settings; verified console output and the declared log file
- [x] App construction takes the environment declaration and selects the app's section using its own name; Fleet declares Hosts and holds only its host rows (RAN 0e342ca65): its own glob, load and render are gone, and its callers read gppu's glob; `Fleet.values`, what a configuration's Jinja reads for a row, came back with the Fleet tools (RAN b071600bb)
- [x] App's environment is optional, and a declared environment loads before the app starts, AsyncApp's init included; an app with none starts with empty configuration
- [x] Env and every app load through one loader, `_config_load` on `mixin_Config`: `Env.init` gives it the environment file, an app its own YAML file (`config=`, independent from the environment) or else its section; `_config_from_key`, `_config_from_dict` and `_config_copy` are gone
- [x] The loader applies templates: `_config_load` fills the Jinja that reads only `glob`, `glob_int`, `glob_list` or `glob_dict`; Hosts' four OTEL endpoints fill at load, Creekview loads unchanged, and Hosts' S1 mounts are generated from `locations` (RAN cecdd4e00), identical to the hand-written rows
- [x] Env and State are each one instance; Env's methods read `self`
- [x] `glob`, `glob_int`, `glob_list`, `glob_dict` are globals; every caller in gppu, RAN, CRAP, IoT and Y2 uses them
- [x] No configuration comparison and no change listeners: `_config_changes`, `changed_paths`, `on_change` removed
- [x] Env does not initialize from itself: `from_env` is gone, and Env's configuration is read for it by App construction
  - Tried: Env reading the nearest `config.yaml` above the program at construction. The Hosts TUI found nothing, Y2 found `y2/config.yaml` with its `topology:` line, and file_indexer's stale `CRAP/Projects/file_indexer/config.yaml` broke `import gppu`; not committed
  - Compared over every `from_env` caller (`D:\Work\11\13\env-location\rows.txt`): neither the nearest `config.yaml` nor the nearest `_config/config.yaml` reaches Creekview's `_creekview.yaml`, and Linked Data, the lake, CRAP's ETLs, CCTV and the Kuma and devops scripts sit in neither of the two environments
  - Settled by SPEC: they read Hosts, and Y2's apps read Creekview; nothing walks folders. Y2 main does not load Creekview on gppu master today, because master no longer reads its `topology:` line. The "Next" written here (a program declares Creekview by an import or its first line) is superseded by SPEC: app initialization takes its environment
- [x] No topology: `topology` parameter and `_topology_file` removed
- [x] `APP`, `_app` and `init` removed
- [x] Nothing outside `mixin_Config` reads `_my`
- [x] `_config_file`, `_program_name`, `_main`, `_resolve_app_path` removed with `from_env`
- [x] gppu's tests give Env its configuration as a program does: the `ran` fixture writes RAN's `config.yaml` in a temporary home and an app declaring RAN loads it; a test of an app's own reading gives the app `config=`. gppu's examples carry their configuration inline in `MANIFEST` and load it with `App(config=__file__)`; `handlers.yaml` and `desktop.yaml` are gone. Still on removed calls: `test_update_by_y2path` (`Env.update_config`, with AppService's MQTT configuration) and conftest's `ld` fixture (`Env._load_dict`, skipped without `LD_TEST_DSN`)
- [x] The command line overrides the app, not Env: `Env.from_argv` removed, and `App(argv=...)` puts the command line over the app's own configuration; Preservator and `list-sessions.py` take it (RAN)
- [x] The environment is RAN, `RAN/_config/config.yaml`, where Alex moved Hosts' configuration: the Hosts TUI, Fleet, craptui, gppu's tests, `examples/basic.py` and the launcher example declare `environment='RAN'`; `topology/locations.yaml` and `topology/connections.yaml` sit where `config.yaml` includes them

## Templates
- [x] The two kinds of templates are gppu's: loading fills the Jinja that reads only the configuration, and leaves `$` text as written for the app, which fills it with `template_populate` (`test_loading_fills_the_jinja_that_reads_only_glob`, `test_loading_keeps_literal_strings`, `test_template`)
- [x] gppu's template code is `render_template` and `apply_template`: `TemplateSet`, `jinja_document` and `dict_template_populate` are gone. A Container's naming templates render from an overlay of gppu's `jinja` over their mapping; the catalog stacks the templates a row names, one or a list in order, each with `apply_template`, and renders their Jinja and the row's row-reading Jinja with the row (`test_catalog_configuration`). The lake's stored configuration, which stacks templates and declares `refs`, resolves in the lake (`graph_configuration.resolve_row`), identically to TemplateSet on every stored table; the lake's sources and Dagster definitions, the LinkML Dagster runtime and admin_ui render with the overlay, which runs on 3.7.4 and later (RAN 4ef4cc8d7, CRAP 334ddfdb)
- [x] Generators are gone, their Jinja on the templates: Creekview has none, and Y2 main, live in the house since 2026-11-13 23:40 on gppu 3.7.4, builds every object without them; the Insteon button patch landed with that deploy
- [x] Creekview's `templates:` are named templates that the loader merges into a row whose `template:` names one; Creekview has no behavior, `base_object` or generator configuration
- [ ] Y2's own template code goes: its template module, `load_templates`, `construct_template` and `render_config` are gone, and Y2 renders with gppu's `render_template`. Left: `base_object` and `object_from_base`, which build an entity from its row

## State and Runtime
- [x] State is a plain object: `State.get(path)`, `State.set(path, value)`
  - gppu's `State` and `Runtime` are commented out in `gppu/gppu.py` and no longer exported (2026-11-13)
- [x] `paths_meet` and State's listeners removed
- [ ] Y2's State and Runtime are gppu's. gppu has neither now; their tests are in `archive/tests/test_state.py`
  - [x] Y2's timers are gppu AsyncApp's, and only AsyncApp's: `run_later` (re-armed by key), `run_every`, `cancel_timer`, `cancel_timers`, their handles and the one thread that holds them, and an app's armed timers are public (`timers`, `h_timeouts`)
  - [x] App has no init of its own: it loads, its environment then its own configuration, as a step of `_DC`'s init. Linked Data's API still runs its database's init before it
  - [x] Y2's App is a gppu AsyncApp, and Y2's program an AsyncApp again; y2 main keeps no timer code or callback wrapper of its own, builds the runtime it built before and fails only the tests it failed before. The house switches at y2's next release, which restarts y2
  - [x] Y2 uses Env and has no Environment of its own: Y2 loads IoT through Env, reads `y2/dry_run` with glob, and its API sets `Env.app_path`; State is no entity. y2 builds the runtime it built before
  - [x] Y2's Runtime is gppu's (`gppu.iot`): moved whole, its apps, registries and listeners; the `immediate` state listener nobody called is gone, and Y2's program registers State with it. y2 keeps no copy
  - [x] Y2's App steps through AsyncApp's `init`, `load`, `start` and `stop`, not its own: its `initialize` is its part of `init`, at construction as before, and its teardown its part of `stop`
  - [x] Y2's admin UI and its per-app status clients have no `_spawn` of their own: they spawn on State's, which holds Y2's tasks on its loop and is the spawn gppu's MQTT mixin asks its host for. A failed admin bind stays the UI's, as in the house today
  - [ ] Y2's State is gppu's
    - Y2's State names Y2's `Entity`, `YEntity` and `YGroup` in four places (a stand-in for an unknown eid, an unknown eid's state, an entity's indicator, the group check), and its base is Y2's App; gppu cannot import Y2
    - No entity in Y2's dry runtime has State as its `api`; every one has its own app's

## Y2's tests, passing before y2 is deployed
- [x] The footer, admin collection, Home Assistant compiler, Z-Wave, AV, pool-light, cloud occupancy and app-shape tests read what Y2 reads now; the AV test expects the AV objects the running Y2 serves
- [x] Kasa's readings and Insteon's buttons and indicators: Creekview dropped two headphone readings on 2026-11-06 and filled seven keypad slots, four with new paths, on 2026-11-01; the running Y2 serves the same
- [x] Hue, Sensibo and the scene light contract write the compilers' output to their own folder through `y2/trace_folder`, which Y2 reads (they patched a top-level key, so on a host with Creekview's `generated` folder the compilers would write into it); the AO lamps button is ao1's 2, as Creekview has it since 2026-11-01
- [x] The admin UI's Kasa positions: the test starts Kasa as Y2 does, then cancels every timer its start armed
- [x] Insteon's scene links: the fixture follows Creekview's 2026-11-01 AO change (IoT 1eb5d007), and Y2 main reproduces every other recorded file
- [x] Homebridge's both-ways check: rows list the commands they accept
- [ ] The Creekview validator, on Windows, checks `D:\Dev`'s Creekview instead of its candidate copy, because `Env.init` places IoT under `D:\Dev` there; on the house it reads the candidate
- [ ] Homebridge's front camera bridge: Y2 main adds the two Garage Shelf cameras Creekview declares since 2026-10-31, which `IoT/homebridge/front/config.json` lacks; otherwise identical
- [ ] IoT's `tests/test_tod_actions.py`: Creekview has Y2's TOD reactions commented out, as `i-tod.sh` runs the time of day; two tests drive those reactions, and Y2's TOD actions miss some of the script's targets in all four modes

## Y2 entity
- [ ] Y2's entity (`y2entity.py`) is part of gppu

## Apps
- [x] AsyncApp is an App: its name and own configuration come from App's construction
- [x] App in `gppu.py`, AsyncApp in `app.py`; MqttApp and AppService in `iot.py`; `app_service.py` gone
- [x] AppService's startup read (`from_mqtt`) and its running service are one class
- [x] AsyncApp launches a process and runs work in parallel: `launch` hands each line of a process's output to the caller, and `run_parallel` starts every unit at once, holding back one that clashes with a running one. They are the Fleet grid's, moved out of the TUI: on 3.7.4 the grid calls them on itself and RAN `Hosts/fleet.py` has no copy. The timers (`run_later`, `run_every`) are AsyncApp's, taken from Y2's App
- [x] TUIApp is an AsyncApp: an app's data through `_DC`, AsyncApp's methods, and its TaskGroup open while Textual runs it. Textual keeps `run`, its repr, identity and the names it annotates (`_DC` had made a property of Textual's `TOOLTIP_DELAY`). It runs AsyncApp's load and start as AsyncApp's, so a TUI's own `load` or `start` (the handler browser's, the Fleet grid's) stays its own. A launcher's `SECTIONS` is a class setting (`ClassVar`), so `_DC` leaves it alone; gppu's pickers, `Selector` and `DetailedSelector`, are TUI apps whose arguments are their data
- [ ] Configuration from MQTT read in one place: one listener on a topic prefix, the last part of the topic names the section; no topic-to-path table, no `from_mqtt` startup copy
- [x] TUI apps read inline configs through `dict_from_yml`: a `.py`'s global `MANIFEST`, a `.cmd`'s opening `::` lines, a `.ps1`'s opening `.NOTES`; each equals the YAML it replaced. The Hosts launcher lists `synology-mount.py`, `mapper.cmd` and `tray-control.ps1`, and w11's lists `w11-events.py` and `w11-onedrive.py`. A launcher's `apps:` and `utilities:` are its own configuration, an App given to `load_registry`, and Edit Config opens its `CONFIG`; the Hosts TUI, craptui and w11 construct it. `examples/sessions_clean.py` runs on master as an app whose own configuration is its `MANIFEST`, with the command line over it

## Switches at the next gppu release
The release and the y2 deploy are one window. In order:
1. gppu is released from master by its GitHub Action; alex-pc's `~/.venv` takes it, and the Hosts TUI is opened on it.
2. y2's image is rebuilt on `gppu/latest`, its suite run, and y2 deployed, which restarts it in the house.
3. In the same window, with that y2: Creekview's `ui/ui.yaml` loses its inner `ui:` level, the old block kept commented out, and `y2/ui/data.py` drops `self.data |= self.my('ui')`. Neither is written yet.
4. RAN: the `::` lines of `Hosts/mapper.cmd` and the `.NOTES` of `Hosts/tray-control.ps1` go, their `MANIFEST` staying; Preservator and the Fleet grid switch, by the Preservator session.
5. Every other host that runs a gppu tool takes the release before it runs one: the Mac, trix and five have 3.6, seven has none.
What stops at the release until it is switched is listed below.

These move in the same commit as the release. gppu 3.7.7 is released and alex-pc's `~/.venv` runs it, so the Hosts TUI opens there on the RAN environment; a program below that still calls `from_argv`, `from_env` or `from_dict` stops on alex-pc until it switches. Before 3.7.2, the Hosts tools that construct Fleet (Preservator, configs, list-sessions, list-sessions2, sessions-clean, start-page) ran on neither gppu. Still to switch:
- Preservator: switched in RAN, and on 3.7.5 its steps run on alex-pc: it preserved alex-pc's LLM logs, browser history and shell history to the Lake on 2026-11-14. RAN `Hosts/preservator/preservator.py` is the one Preservator, reading the `preservator` section; its other versions are archived (RAN `archive/Hosts/preservator`, CRAP `archive/Processes/preservator`). It stores each file by `gppu.fs.file_path(type, name, ...)`, which reads where each type of file is stored from the Lake's row in RAN `_config/topology/locations.yaml` (`locations/lake/folders`), with no function per kind; on alex-pc's own files those lines place every file where the version before it did (`D:\Work\11\13\lake-templates`). Another host runs it there over ssh, which needs current gppu on that host: the Mac, trix and five have 3.6, seven has none, five has no Lake mount
- display-control (`IoT/PCC`): `on_change` and `AppService.update_config`/`changed_paths` callers; MQTT configuration by topic prefix
- The programs that write the command line over Env: display-control, Intune's three scripts, `setup-ld-monitors.py`, `operon_remove.py`, `sync_to_operon.py` and `openapi_query.py`
- Every `Env.from_env` caller in RAN, CRAP, IoT and Y2, and the "Configuration without an app" line in the global CLAUDE.md that names `Env.from_env`
- Every reader of `Env.data`, which is `Env._my` now, reads `glob_dict('')`: lake's `graph_configuration.py` and `m365/config.py`, display-control and its Intune scripts, and the Preservator, Session Manager and FileIndexer tests

- RAN `Hosts/mapper.cmd` and `Hosts/tray-control.ps1` carry `MANIFEST` and, beside it, the `::` lines and `.NOTES` the released gppu reads; the older lines go at the release (RAN aa2f5939d: the Hosts launcher lists every item identically on 3.7.9 and on master)
- y2 main needs the gppu after 3.7.9 (`y2/NOTE_gppu-rebuild-261121.md`)
- Preservator (RAN `Hosts/preservator/preservator.py`), with the Fleet grid (`Hosts/configure-all/fleet-tui.py` calls `Preservator().configuration()[0]`, `record_start`, `record_result`) and its tests: switched in the same window as the release by the Preservator session, which is told before the release is cut
- A script's MANIFEST no longer takes `!include`: it is text, and an include reads beside a file. w11-events reads its `error_rules.yaml` in code
- A caller of `Logger.enable_file_logging(name, log_dir=...)`, of `mixin_Config._config_load` or of `Env._my`: none is left in gppu, y2 or RAN/Hosts

## Found outside this task
- Hosts: `configs.py`'s and `start-page.py`'s `load_config` read `fleet.platforms`, which Fleet has not had since 2026-09-30
- Hosts: `hosts.yaml` lost s1's, s9's and yellow's `mount` in the move to `RAN/_config`, so `server_mounts` rendered `None/Lake` and the like; the three lines are back (RAN b071600bb)
- Fixed: gppu: `test_tui_logging`'s file-and-trace-rules and shared-log-screens tests pass, and gppu's whole suite passes on master
- Fixed: Hosts: `system_updates` and `sync_repos` name the runbooks' `update` and `sync_repos` commands, whose task scripts Alex deleted: apt on WSL and Linux as before `half_configured` was invented, UniGetUI's own winget on Windows, brew on the Mac, and a zsh sync for the Mac; every host of the Update presets renders
- Hosts: the Fleet grid's Preserve cells fail on alex-pc's gppu 3.7.3, whose `file_path` takes the older arguments; they need the release carrying b25d2b8, whose tests fail nothing that master did not already fail
- Hosts: all-all's Checkup and clean-sessions modes name a runbook and a task that `runbooks.yaml` no longer has
- Hosts TUI: Fleet, Preserve and Configs are on the Fleet section again, and render-config in Fleet tools: `configure-all`, `render-config`, `harness` and the Configs files came back from the archive and read Fleet's rows, `Fleet.values` and gppu's glob and Jinja (RAN b071600bb). Start page stays archived. PC Control launches `IoT/PCC/pcc-service.py`, which stops at `Env.from_env` until display-control is switched
- Fixed: Preservator: the LLM step's `logs` exclusion, meant for OpenClaw, also left out Agy's transcripts, which sit in `.system_generated/logs`; a session folder is now copied whole whatever the step excludes
- craptui: `craptui.yaml` names `gd-video-ripper.yaml`, removed with GD Video Ripper, so craptui does not open
- RAN: `Skills/devops/scripts/y2-compare.py` reads `Runtime.services`, which Y2's Runtime does not have
- Y2: State keeps every message it publishes in `State.published`, which only tests read, so the list grows for the life of the process
- IoT: Creekview's `generated/i1-scenes.yaml` still links the AO lamps to AO Pendant, which Creekview's scenes dropped on 2026-11-01; that day's commit edited the file by hand rather than compiling it
- gppu examples: their `MANIFEST` names `D:/TextLake/.catalog`, which has no host folder, so `handler_ls` and the handler browser stop there
- w11: with `W11_APP_DIR` unset, the launcher reads its 2026-03-16 copies in `~/.gppu/w11`, not the repository's scripts; `w11/default_config/w11.yaml`, which seeds them, still names the deleted `w11-events.yaml` and `w11-onedrive.yaml`
- gppufs: its YAML does not go through the one parsing process: `fs/catalog.py` reads the catalog's sources, a host's `replicas.yaml` and its `locations.yaml` with `yaml.safe_load`, `fs/__init__.py` a container's merge rules, and `fs/handlers.py` Markdown frontmatter with a loader of its own
- Linked Data's tests: `tests/test_ld.py` and conftest's `ld` fixture read `Env._my` and call the removed `Env._load_dict`; RAN `Systems/ld/fileindexer/tests` set `Env._my`
- Y2: `news/news.py` reads its configuration in `setup`, which no step calls, and Creekview has no `news` section
- Y2: `ui/data.py` copies `ui/ui` into its own data, because `ui.yaml` nests a `ui:` key inside the `ui` section
- Fixed: RAN: `server_mounts` is a row per location, each an expression that loading fills from `locations` and S1's host row, and `sessionfolder` is one expression (RAN e592787e9, 3847a7eec); the loaded configuration is identical on master and on 3.7.9, and every session file is placed where it was
- gppu: handlers that turn a failure into a value, none changed: `mixin_Rest._born` (TypeError to an empty string), `mixin_Mqtt`'s offline publish on disconnect and its JSON decode of a payload, `HTTPControl` and `JSONHTTPControl` (a failed request or a body that is not JSON to None, which Y2's callers branch on), `Vault`'s provider probe
- The scripts that still call the removed `Env.from_env`, `Env.from_dict`, `Env._load_dict` or read `Env.data`, about 110 in CRAP, IoT's CCTV-detective and RAN's Systems and Skills; CRAP's `prior/` trees; CRAP's `_Base` and `_PGBase` users: `_Base` is still the logger with the configuration's readers, and the readers now read a `_DC`'s data, which those classes do not have; none of them calls `my`
