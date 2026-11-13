# Configuration

An app declares its environment by name at construction: `Hosts` or `IoT`. The environment is optional. When an app has one, the environment loads first, then the app starts on its own section of it.

```python
from gppu import App, glob

class Example(App):
    pass

app = Example(environment='Hosts')
app.my('mode')          # the `example:` section of Hosts
glob('hosts')           # the rest of Hosts
```

The app already has its identity: `Example` selects `example`, and `Fleet` selects `fleet`. An explicit name remains an override for existing callers. The app's section is its own copy.

An app's own configuration is independent from the environment: `Example(config='example.yaml')` loads that YAML file as the app's own, whether or not it declares an environment. An app given no file loads its section of the environment.

Env and every app load through the same code, `_config_load(source)` on `mixin_Config`: a YAML file, or a section already loaded, becomes the object's own configuration as a copy.

## Env.init

App construction calls `Env.init(environment=...)`. Env is the global singleton app; nothing else loads it.

- It sets `host`, `os`, `user` and `home`, so an app without an environment has them too.
- A declared name selects one YAML file: Hosts is `RAN/Hosts/_config/config.yaml`, IoT is `IoT/_Creekview/_creekview.yaml`. The path is under `D:\Dev` on Windows and under the home folder elsewhere. YAML `!include` paths are relative to the file that includes them.
- `_config_load` reads the file into Env, so it becomes the configuration that `glob(...)` reads; its `log_file` and `trace_rules` then apply to gppu's logger.
- The environment loads once. Later apps share it, with or without a declaration, until `Env.reset()`.
- An unknown name, a missing file and invalid YAML raise. Nothing searches folders or guesses a program's configuration.

An app without an environment, and none loaded, starts with empty configuration; `glob(...)` returns None.

`examples/basic.py` declares Hosts; its Info and Debug lines follow that file's `trace_rules` and `log_file`. Run it from the gppu repository with `python -m examples.basic`.

## Templates

`jinja_template(node, **values)` renders strings, lists and mappings, including mapping keys. Jinja expressions return native objects; plain strings keep their type. Empty rendered keys are omitted, supporting Fleet's conditional configuration keys. Missing Jinja inputs raise. Loading leaves templates intact so Fleet can render them with the selected host's values later.
