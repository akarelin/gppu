# Configuration

`Env.configure(source)` reads the process's shared environment. `source` is a mapping or the declared YAML entry point; YAML `!include` paths are relative to the file that includes them. Missing files and invalid YAML raise directly. Nothing searches parent folders or guesses a program's configuration.

```python
from gppu import App, Env, glob

Env.configure({'shared': {'enabled': True}, 'example': {'mode': 'review'}})
app = App(name='example')
assert app.my('mode') == 'review'
assert glob('shared/enabled') is True
```

`configure` is the same method on Env and apps, inherited from `mixin_Config`. It replaces configuration with an independent copy. An app starts with the section under its name; `app.configure(source)` replaces only that app's configuration. The environment's `initialized` flag is set after loading. A declared `log_file` enables GPPU file logging.

The environment's entry point owns its location. `RAN/Hosts/fleet.py` declares `_config/config.yaml` beside itself, loads it once with `Env.configure`, and returns a `Fleet` app. Callers continue to use `fleet.load(name)` without knowing where configuration lives. This port requires the development GPPU API; the installed 3.7.0 release has the earlier loading API.

`jinja_template(node, **values)` renders strings, lists and mappings, including mapping keys. Jinja expressions return native objects; plain strings keep their type. Empty rendered keys are omitted, supporting Fleet's conditional configuration keys. Missing Jinja inputs raise. Loading leaves templates intact so Fleet can render them with the selected host's values later.

Verification covers relative YAML includes, missing declared files, replacement without modifying input, app section isolation, literal paths and dollar expressions, conditional keys, and existing Jinja/YAML tests. A read-only comparison against Fleet's previous renderer verifies the actual Hosts configuration's rendered values and selections without changing configuration.
