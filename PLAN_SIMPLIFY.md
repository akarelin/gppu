# gppu simplification

Goal: gppu provides Env, State and Runtime, so Y2 only creates apps that share one State and one Env. Env is the global singleton app; it loads like any app and never initializes from itself. Alex's instructions are in [SPEC.md](SPEC.md).

## Env
- [x] App declares `environment='Hosts'` or `environment='IoT'`; `Env.init` selects the corresponding YAML file under `D:\Dev` on Windows and the home folder elsewhere. Basic runs with Hosts
- [x] App construction calls `Env.init(environment=...)`: it sets `host`, `os`, `user` and `home`, loads the declared environment once and applies its `log_file` and `trace_rules`; later apps share it until `Env.reset()`. An unknown name or a missing file raises. `Env.load` and `Env.resolve_path` are commented out
- [x] `examples/basic.py` uses Hosts, with Info and Debug output controlled by Hosts' logging settings; verified console output and the declared log file
- [x] App construction takes the environment declaration and selects the app's section using its own name; Fleet declares Hosts and holds only its host rows (RAN 0e342ca65): its own glob, load, render and values are gone, and its callers read gppu's glob
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
- [ ] gppu's tests that set the environment with `Env.from_dict` or `Env.from_env` have no public way to set one now that Env takes only Hosts or IoT
- [x] The command line overrides the app, not Env: `Env.from_argv` removed, and `App(argv=...)` puts the command line over the app's own configuration; Preservator and `list-sessions.py` take it (RAN)

## Templates
- [ ] Env reads a templated configuration with the two kinds of templates, Jinja and the basic `$` one, so `glob` and `self.my` return it filled in. (Env's `$` pass gets no values today; it once filled `$code_path`, `$shared_data_path` and `$shared_data`.)
- [ ] `TemplateSet` (template, generator, behavior, refs) goes; gppu's `fs` catalog, lake and objects use Jinja
- [ ] Generators go; their Jinja moves onto the templates (in progress)
  - [x] Groups, AV and the z2 ring: macros the templates call; the construction dump shows no difference
  - [x] Insteon templates and motion sensors: Jinja values on the templates, the sensors' posts a topic template; no difference
  - [x] `TemplateSet` has no generators or behaviors; the lake passes none
  - [x] Y2 builds the base object from a template's data, not its unrendered Jinja (y2 6620f62), so a template can name a button after its base object is built
  - [ ] The Insteon button's generator: `D:\Work\11\12\creekview-generators\insteon-button-release.patch` lands with the Y2 deploy from main, at the same y2 restart; on Y2 main it constructs identically, on the running v6.1.7.5730 it changes the buttons' state topics. The live tree takes IoT master first: it constructs identically on 5730, and Y2 main needs it
    - Y2 main on released gppu: builds every object as 5730 does, validates with and without the patch, and fails no test 5730 passes (fixed today: apps shared one configuration dict, the inspector page's totals, tests using `Env.update_config`)
    - The release now verifies the live tree as y2 starts it (`AppRosterTest`), so a tree the image cannot run fails the release instead of y2's start
    - Not built: the Release for `y2` from main ran twice on 2026-11-13 and published nothing. The first run failed on Y2 main's own tests: after 6620f62, every test that rebuilds State needs the topology's macros in its Env (fixed in y2 89e7d34 and 7c19ccc). The second run failed `AppRosterTest`: iot's live `y2.yaml` gives Tuya and Sensibo no `key`, so the live tree is behind IoT master (read on the y2-ui Creekview page). It needs IoT master pulled on iot, then a Release run and the stack deploy; SSH to iot is refused for this session
  - [ ] Then Y2's generator branch in `construct_template`, the `generators` registration and the `generators` fixture in `tests/test_semantic_layer.py` go
- [ ] Creekview's `templates:` hold named Jinja templates that return the object, and `template:` names one; behavior and `base_object` go
- [ ] Y2's own template code goes: `templates.py`, `load_templates`, `base_object`, `object_from_base`, `construct_template`, `render_config`

## State and Runtime
- [x] State is a plain object: `State.get(path)`, `State.set(path, value)`
  - gppu's `State` and `Runtime` are commented out in `gppu/gppu.py` and no longer exported (2026-11-13)
- [x] `paths_meet` and State's listeners removed
- [ ] Y2's State and Runtime are gppu's

## Y2 entity
- [ ] Y2's entity (`y2entity.py`) is part of gppu

## Apps
- [x] AsyncApp is an App: its name and own configuration come from App's construction
- [x] App in `gppu.py`, AsyncApp in `app.py`; MqttApp and AppService in `iot.py`; `app_service.py` gone
- [x] AppService's startup read (`from_mqtt`) and its running service are one class
- [ ] Configuration from MQTT read in one place: one listener on a topic prefix, the last part of the topic names the section; no topic-to-path table, no `from_mqtt` startup copy
- [x] TUI apps read inline configs through `dict_from_yml`: a `.py`'s global `MANIFEST`, a `.cmd`'s opening `::` lines, a `.ps1`'s opening `.NOTES`; each equals the YAML it replaced. The Hosts launcher lists `synology-mount.py`, `mapper.cmd` and `tray-control.ps1`, and w11's lists `w11-events.py` and `w11-onedrive.py`. A launcher's `apps:` and `utilities:` are its own configuration, an App given to `load_registry`, and Edit Config opens its `CONFIG`; the Hosts TUI, craptui and w11 construct it. `examples/sessions_clean.py` runs on master as an app whose own configuration is its `MANIFEST`, with the command line over it

## Switches at the next gppu release
These move in the same commit as the release. gppu 3.7.2 is released and alex-pc's `~/.venv` runs it, so the Hosts TUI opens there; a program below that still calls `from_argv`, `from_env` or `from_dict` stops on alex-pc until it switches. Before 3.7.2, the Hosts tools that construct Fleet (Preservator, configs, list-sessions, list-sessions2, sessions-clean, start-page) ran on neither gppu. Still to switch:
- Preservator: `self.my('config')` and `self.my('steps')`
- display-control (`IoT/PCC`): `on_change` and `AppService.update_config`/`changed_paths` callers; MQTT configuration by topic prefix
- The programs that write the command line over Env: display-control, Intune's three scripts, `setup-ld-monitors.py`, `operon_remove.py`, `sync_to_operon.py` and `openapi_query.py`
- Every `Env.from_env` caller in RAN, CRAP, IoT and Y2, and the "Configuration without an app" line in the global CLAUDE.md that names `Env.from_env`
- `TemplateSet`'s callers outside gppu use Jinja: lake's `graph_configuration.py`, `sources` and Dagster definitions, the LinkML Dagster runtime, admin_ui's `file_configuration.py`
- Creekview's `generator`, behavior and `base_object` configuration, with Y2's release
- Y2's `y2app.py` calls `_config_from_dict`; it calls `_config_load`
- Every reader of `Env.data`, which is `Env._my` now, reads `glob_dict('')`: lake's `graph_configuration.py` and `m365/config.py`, display-control and its Intune scripts, Y2's `ui/creekview.py`, and the Preservator, Session Manager and FileIndexer tests

## Found outside this task
- Y2: `test_insteon`, `test_kasa2mqtt`, `test_scene_light_contract` and `test_creekview_editor` fail each run on its own, on the running v6.1.7.5730 and on main alike; none is in the Release's verify step
- Hosts: `configs.py`'s and `start-page.py`'s `load_config` read `fleet.platforms`, which Fleet has not had since 2026-09-30
- gppu: `test_tui_logging`'s file-and-trace-rules and shared-log-screens tests fail on master as it is
- Hosts TUI: Fleet, Preserve and Configs launched `configure-all`'s scripts, archived 2026-11-11, and choosing one crashed the menu; they are commented out of `tui.yaml`. PC Control launches `IoT/PCC/pcc-service.py`, which stops at `Env.from_env` until display-control is switched
- craptui: `craptui.yaml` names `gd-video-ripper.yaml`, removed with GD Video Ripper, so craptui does not open
- w11: with `W11_APP_DIR` unset, the launcher reads its 2026-03-16 copies in `~/.gppu/w11`, not the repository's scripts; `w11/default_config/w11.yaml`, which seeds them, still names the deleted `w11-events.yaml` and `w11-onedrive.yaml`
