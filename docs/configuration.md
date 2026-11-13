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

The app already has its identity: `Example` selects `example`, and `Fleet` selects `fleet`. An explicit name remains an override for existing callers. The shared configuration mixin loads the declared environment before selecting that section; Env uses the mixin's same dictionary-loading implementation. The input and the app's own section are independent copies. Later apps can omit the declaration and share the loaded Env. The first app must provide it; otherwise construction raises. Supplying a declaration again replaces the environment. A declared `log_file` enables GPPU file logging.

The environment owns its location. `RAN/Hosts/environment.py` declares Hosts from its repository's `_config/config.yaml`. Fleet receives that declaration in its constructor, without its caller supplying an app name or loading Env separately. `fleet.load()` returns the app and shares an already loaded environment on later calls. This port requires the development GPPU API; the installed 3.7.0 release has the earlier loading API.

`jinja_template(node, **values)` renders strings, lists and mappings, including mapping keys. Jinja expressions return native objects; plain strings keep their type. Empty rendered keys are omitted, supporting Fleet's conditional configuration keys. Missing Jinja inputs raise. Loading leaves templates intact so Fleet can render them with the selected host's values later.

Verification covers relative YAML includes, missing declared files, replacement without modifying input, app section isolation, literal paths and dollar expressions, conditional keys, and existing Jinja/YAML tests. A read-only comparison against Fleet's previous renderer verifies the actual Hosts configuration's rendered values and selections without changing configuration.
