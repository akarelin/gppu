---
fileClass: Document
created: "2026-09-16 2040"
updated: "2026-09-16 2040"
generated: { by: "Claude/fable-5.1", at: "2026-09-16T20:40:00-07:00" }
---

# Environment and State

Alex, 2026-09-16: "Currently all y2 apps share state and config. I want to do the same for python utils and tuis. Have every app on load already have all it needs. Doing it with heavy templating, full referential integrity, minimize general code in utilities. Move as much as reasonable to configs." On construction: "Build default object dict from uid. Update dict with customization for particular hosts (very rare). build object from dict. register in State object if a service".

`gppu.Environment` is the basic level, with no configuration file: `platform` (`windows`, `wsl`, `debian`, `macos`, the vocabulary of the shared configuration), `host`, `user`, `home`, `os`, and `trace()`. `Environment.from_env(name, app_path)` loads the app's configuration the way `Env.from_env` does and then constructs `State` from it; an `App` does both when it is constructed, so a utility on the app object has everything at load.

An app's `config.yaml` brings the shared configuration in with one line, and nothing in the app reads it as a file:

```yaml
!include ../../_config/_ran.yaml

browse:
  addresses: [sd://SD.Lake/inbox]
```

## Tables and rows

A section that carries `templates` is a table. Every other mapping in it is a row keyed by its uid; `macros` and `generators` beside them belong to the section. Tables are constructed in the order the configuration lists them, and a table constructed later sees an earlier one resolved, so a location's rules may read what a connection's template computed.

Per row: the templates it names build the default dict from the uid; the row updates it with what differs; the dict is checked against the tables the templates say it references; the object is built by the class the dict's `kind` names — the app that cares registers it with `State.register(Location=Location)`, any other app gets a plain `_DC` carrying the kind; a row marked `service: true` also registers in `State.services`. Construction runs once, at startup.

```python
from gppu import App, Environment, State
from gppu.gppu import _DC

class Location(_DC):
  name: str
  local: str

State.register(Location=Location)

class Browse(App):
  def main(self):
    for uid, location in State.locations.items(): print(uid, location.local)
```

`State.locations`, `State.hosts`, `State.connections` — one attribute per table, uid to object. Lookups through `Environment.glob(path)`, `glob_list`, `glob_dict` are strict: a missing key raises, nothing has a default. A query is a Jinja filter in a template or a comprehension over a table, not a method.

## The configuration answers

What a utility used to compute for itself is a macro of the configuration, called by name. `Environment.macro(section, name)` returns the macro; `Environment.answer(...)` returns what it says as text. The locations table defines the ones every utility asks:

| Call | Answers |
| --- | --- |
| `Environment.place(uid, host=, platform=)` | where a location is on a host; this host and platform unless told otherwise |
| `Environment.folder(uid, inside, ...)` | a named folder of a location, where the location is |
| `Environment.uri(uid, interface)` | the location's address on one interface, in the grammar its connection's provider declares |
| `Environment.location_of(address)` | the uid of the location an address is inside of |
| `Environment.local_of(address, ...)` | the path on a host of an address; `''` when the host does not reach it |

`examples/config` is the reference: `_config/_ran.yaml` in the `_creekview.yaml` shape with `platforms`, `resources` (one row per URI scheme: the resource class and the address grammar), `connections` (the boxes and tenants, providers as templates), `hosts` and `locations` beside it, each carrying its templates with its rows. A location's templates carry the logic Alex stated: a file service provides files and folders, the row computes its canonical address, its mirrors and its place on this host. `browse.py` is an `App` that lists every location so and walks the addresses of its own section through gppufs. Run it with no arguments.
