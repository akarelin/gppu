# gppu simplification

Goal: gppu provides Env, State and Runtime, so Y2 only creates apps that share one State and one Env. Env is the global singleton app; it loads like any app and never initializes from itself. Alex's instructions are in [SPEC.md](SPEC.md).

## Env
- [x] Env and State are each one instance; Env's methods read `self`
- [x] `glob`, `glob_int`, `glob_list`, `glob_dict` are globals; every caller in gppu, RAN, CRAP, IoT and Y2 uses them
- [x] No configuration comparison and no change listeners: `_config_changes`, `changed_paths`, `on_change` removed
- [ ] Env does not initialize from itself: `from_env` goes, Env's configuration is read for it at construction like an app's
- [x] No topology: `topology` parameter and `_topology_file` removed
- [x] `APP`, `_app` and `init` removed
- [x] Nothing outside `mixin_Config` reads `_my`
- [ ] `_config_file`, `_program_name`, `_main`, `_resolve_app_path` removed with `from_env`
- [ ] The command line overrides the app, not Env: `Env.from_argv` removed, the app's own configuration takes the command line

## Templates
- [ ] Env reads a templated configuration with the two kinds of templates, Jinja and the basic `$` one, so `glob` and `self.my` return it filled in. (Env's `$` pass gets no values today; it once filled `$code_path`, `$shared_data_path` and `$shared_data`.)
- [ ] `TemplateSet` (template, generator, behavior, refs) goes; gppu's `fs` catalog, lake and objects use Jinja
- [ ] Generators go from Creekview; their Jinja moves onto the templates (in progress)
  - [x] Groups, AV and the z2 ring: macros the templates call; the construction dump shows no difference
  - [ ] Insteon motion sensors: the template's `motion_posts` value calls the helper `motion_posts`, which Y2 reads as a merge with the row's own value; the helper's name changes in Y2, so this lands with Y2's release
  - [ ] Insteon templates (`insteon_kpl`, `insteon_scene`, `insteon_yala_scene`, the entity and button generators)
  - [ ] Y2's generator branch in `construct_template` and the `generators` registration go
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
