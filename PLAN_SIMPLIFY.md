# gppu simplification

Goal: gppu provides Env, State and Runtime, so Y2 only creates apps that share one State and one Env. Env is the global singleton app; it loads like any app and never initializes from itself.

## Env
- [x] Env and State are each one instance; Env's methods read `self`
- [x] `glob`, `glob_int`, `glob_list`, `glob_dict` are globals; every caller in gppu, RAN, CRAP, IoT and Y2 uses them
- [x] No configuration comparison and no change listeners: `_config_changes`, `changed_paths`, `on_change` removed
- [ ] Env does not initialize from itself: `from_env` goes, Env's configuration is read for it at construction like an app's
- [x] No topology: `topology` parameter and `_topology_file` removed
- [x] `APP`, `_app` and `init` removed
- [x] Nothing outside `mixin_Config` reads `_my`
- [ ] Env resolves the configuration's templates when it loads (`TemplateSet`), so `glob` and `self.my` return resolved values; Y2's `load_templates` and fleet's own Jinja go
- [ ] `_config_file`, `_program_name`, `_main`, `_resolve_app_path` removed with `from_env`
- [ ] The command line overrides the app, not Env: `Env.from_argv` removed, the app's own configuration takes the command line

## State and Runtime
- [x] State is a plain object: `State.get(path)`, `State.set(path, value)`
- [x] `paths_meet` and State's listeners removed
- [ ] Y2's State and Runtime are gppu's

## Apps
- [x] AsyncApp is an App: its name and own configuration come from App's construction
- [x] App and AsyncApp in `app.py`; MqttApp and AppService in `iot.py`; `app_service.py` gone
- [x] AppService's startup read (`from_mqtt`) and its running service are one class
- [ ] Configuration from MQTT read in one place: one listener on a topic prefix, the last part of the topic names the section; no topic-to-path table, no `from_mqtt` startup copy

## Switches at the next gppu release
These run on the released gppu today and move in the same commit as the release:
- Preservator: `self.my('config')` and `self.my('steps')`
- display-control (`IoT/PCC`): `on_change` and `AppService.update_config`/`changed_paths` callers; MQTT configuration by topic prefix
- The programs that write the command line over Env: Preservator, `list-sessions.py`, display-control, Intune's three scripts, `setup-ld-monitors.py`, `operon_remove.py`, `sync_to_operon.py`, `openapi_query.py`, gppu's `examples/basic.py` and `examples/sessions_clean.py`
- Every `Env.from_env` caller in RAN, CRAP, IoT and Y2
- Every reader of `Env.data`, which is `Env._my` now, reads `glob_dict('')`: lake's `graph_configuration.py` and `m365/config.py`, display-control and its Intune scripts, Y2's `ui/creekview.py`, and the Preservator, Session Manager and FileIndexer tests
