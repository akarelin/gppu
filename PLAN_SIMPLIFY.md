# gppu simplification

Goal: gppu provides Env, State and Runtime, so Y2 only creates apps that share one State and one Env. Env is the global singleton app; it loads like any app and never initializes from itself. Alex's instructions are in [SPEC.md](SPEC.md).

## Env
- [x] Env and State are each one instance; Env's methods read `self`
- [x] `glob`, `glob_int`, `glob_list`, `glob_dict` are globals; every caller in gppu, RAN, CRAP, IoT and Y2 uses them
- [x] No configuration comparison and no change listeners: `_config_changes`, `changed_paths`, `on_change` removed
- [ ] Env does not initialize from itself: `from_env` goes, Env's configuration is read for it at construction like an app's (in progress)
  - Tried: Env reading the nearest `config.yaml` above the program at construction. The Hosts TUI found nothing, Y2 found `y2/config.yaml` with its `topology:` line, and file_indexer's stale `CRAP/Projects/file_indexer/config.yaml` broke `import gppu`; not committed
  - Compared over every `from_env` caller (`C:\.cache\env-rules\rows.txt`): neither the nearest `config.yaml` nor the nearest `_config/config.yaml` reaches Creekview's `_creekview.yaml`, and Linked Data, the lake, CRAP's ETLs, CCTV and the Kuma and devops scripts sit in neither of the two environments
  - Open: which environment those programs read
- [x] No topology: `topology` parameter and `_topology_file` removed
- [x] `APP`, `_app` and `init` removed
- [x] Nothing outside `mixin_Config` reads `_my`
- [ ] `_config_file`, `_program_name`, `_main`, `_resolve_app_path` removed with `from_env`
- [ ] The command line overrides the app, not Env: `Env.from_argv` removed, the app's own configuration takes the command line

## Templates
- [ ] Env reads a templated configuration with the two kinds of templates, Jinja and the basic `$` one, so `glob` and `self.my` return it filled in. (Env's `$` pass gets no values today; it once filled `$code_path`, `$shared_data_path` and `$shared_data`.)
- [ ] `TemplateSet` (template, generator, behavior, refs) goes; gppu's `fs` catalog, lake and objects use Jinja
- [ ] Generators go; their Jinja moves onto the templates (in progress)
  - [x] Groups, AV and the z2 ring: macros the templates call; the construction dump shows no difference
  - [x] Insteon templates and motion sensors: Jinja values on the templates, the sensors' posts a topic template; no difference
  - [x] `TemplateSet` has no generators or behaviors; the lake passes none
  - [x] Y2 builds the base object from a template's data, not its unrendered Jinja (y2 6620f62), so a template can name a button after its base object is built
  - [ ] The Insteon button's generator: `D:\Work\11\12\creekview-generators\insteon-button-release.patch` lands with the Y2 deploy from main, at the same y2 restart; on Y2 main it constructs identically, on the running v6.1.7.5730 it changes the buttons' state topics. The live tree takes IoT master first: it constructs identically on 5730, and Y2 main needs it
  - [ ] Then Y2's generator branch in `construct_template`, the `generators` registration and the `generators` fixture in `tests/test_semantic_layer.py` go
- [ ] Creekview's `templates:` hold named Jinja templates that return the object, and `template:` names one; behavior and `base_object` go
- [ ] Y2's own template code goes: `templates.py`, `load_templates`, `base_object`, `object_from_base`, `construct_template`, `render_config`; fleet's own Jinja goes

## State and Runtime
- [x] State is a plain object: `State.get(path)`, `State.set(path, value)`
- [x] `paths_meet` and State's listeners removed
- [ ] Y2's State and Runtime are gppu's

## Y2 entity
- [ ] Y2's entity (`y2entity.py`) is part of gppu

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
- `TemplateSet`'s callers outside gppu use Jinja: lake's `graph_configuration.py`, `sources` and Dagster definitions, the LinkML Dagster runtime, admin_ui's `file_configuration.py`
- Creekview's `generator`, behavior and `base_object` configuration, with Y2's release
- Every reader of `Env.data`, which is `Env._my` now, reads `glob_dict('')`: lake's `graph_configuration.py` and `m365/config.py`, display-control and its Intune scripts, Y2's `ui/creekview.py`, and the Preservator, Session Manager and FileIndexer tests
