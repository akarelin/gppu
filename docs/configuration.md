# Configuration

App construction takes the environment declaration. It is a mapping or the declared YAML entry point; YAML `!include` paths are relative to the file that includes them. Missing files and invalid YAML raise directly. Nothing searches parent folders or guesses a program's configuration.

```python
from gppu import App, glob

class Example(App):
    pass

app = Example(environment={'shared': {'enabled': True}, 'example': {'mode': 'review'}})
assert app.my('mode') == 'review'
assert glob('shared/enabled') is True
```

The app already has its identity: `Example` selects `example`, and `Fleet` selects `fleet`. An explicit name remains an override for existing callers. App calls `Env.load(environment)` before selecting its own section. The input and the app's own section are independent copies. The environment is optional: an app without a declaration shares the loaded Env, or starts with empty configuration when none has been loaded. Supplying a declaration again replaces the environment. A declared `log_file` enables GPPU file logging; an invalid path raises.

Code without an app loads the same environment with `Env.load(declaration)`, then reads it with `glob(...)` or `glob_dict('')`. `Env.reset()` clears the configuration. YAML loading preserves dollar expressions and Jinja templates for later rendering.

`trace_rules` is a mapping applied to GPPU's logger when the environment loads. `examples/basic.py` passes `RAN/Hosts/_config/config.yaml` to `Basic`; its Info and Debug calls use that YAML file's `trace_rules` and `log_file`. Run the example from the GPPU repository with `python -m examples.basic`.

An environment is a YAML file, not a module. `Env.resolve_path(path)` constructs a relative filename from the directory containing the program's repository: Git identifies the repository root from the program's location, and the filename names its sibling repository and configuration file. Thus `RAN/Hosts/_config/config.yaml` and `IoT/_Creekview/_creekview.yaml` follow relocated repositories, independently of the working directory. The repositories share a parent directory. Absolute filenames remain absolute. Git and a program inside a repository are required for relative filenames; errors propagate directly. No configuration folders are searched. Fleet passes its YAML filename in its constructor; `fleet.load()` shares the loaded environment on later calls. This port requires the development GPPU API.

`jinja_template(node, **values)` renders strings, lists and mappings, including mapping keys. Jinja expressions return native objects; plain strings keep their type. Empty rendered keys are omitted, supporting Fleet's conditional configuration keys. Missing Jinja inputs raise. Loading leaves templates intact so Fleet can render them with the selected host's values later.

Verification covers relative YAML includes, missing declared files, replacement without modifying input, app section isolation, literal paths and dollar expressions, conditional keys, and existing Jinja/YAML tests. A read-only comparison against Fleet's previous renderer verifies the actual Hosts configuration's rendered values and selections without changing configuration.
