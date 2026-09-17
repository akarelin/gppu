---
fileClass: Document
created: "2026-09-16 2040"
updated: "2026-09-16 2040"
generated: { by: "Claude/fable-5.1", at: "2026-09-16T20:40:00-07:00" }
---

# Environment and State

Alex, 2026-09-16: "Currently all y2 apps share state and config. I want to do the same for python utils and tuis. Have every app on load already have all it needs. Doing it with heavy templating, full referential integrity, minimize general code in utilities. Move as much as reasonable to configs." On construction: "Build default object dict from uid. Update dict with customization for particular hosts (very rare). build object from dict. register in State object if a service".

`gppu.Environment` — one instance, as in Y2 — is the basic level, with no configuration file: `platform` (`windows`, `wsl`, `debian`, `macos`, the vocabulary of the shared configuration), `host`, `user`, `home`, `os`, and `trace()`. `Environment.from_env(name, app_path)` loads the app's configuration the way `Env.from_env` does and then constructs `State` from it; an `App` does both when it is constructed, so a utility on the app object has everything at load.

An app's `config.yaml` brings the shared configuration in with one line, and nothing in the app reads it as a file:

```yaml
!include ../_config/_config.yaml

browse:
  addresses: [sd://SD.Lake/inbox]
```

## Tables and rows

A key of the configuration that carries `templates` is a table. Every other mapping under it is a row keyed by its uid; `macros` and `generators` beside them belong to the table, and a `*_templates` block of named templates to the whole configuration. Tables are constructed in the order the configuration lists them, and a table constructed later sees an earlier one resolved, so a location's rules may read what a connection's template computed.

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

What a utility used to compute for itself is a rule of the configuration — a macro of a table — reached as `Environment.<table>.<rule>(...)`. gppu knows no rule by name; a rule that wants this host and platform says so in its own signature, `{% macro place(uid, host=Environment.host, platform=Environment.platform) %}`. The locations table of the reference configuration defines `place`, `folder`, `uri`, `location_of` and `local_of`; the hosts table defines `ssh(host, platform)`. A rule that says nothing answers `None`.

```python
Environment.locations.place('sd-lake')                    # where it is on this host
Environment.locations.local_of('sd://SD.Lake/inbox')      # the path here of an address
Environment.hosts.ssh('seven', 'debian')                  # ['ssh', '-p', '22', 'alex@7.c.karel.in', 'bash', '-s']
```

`examples/config` is the reference: `examples/_config/_config.yaml`, the root in the `_creekview.yaml` shape with the platforms and `resources` (one row per URI scheme: the resource class and the address grammar), `connections` (the boxes and tenants, providers as templates), `hosts` and `locations` beside it, each carrying its templates with its rows. A location's templates carry the logic Alex stated: a file service provides files and folders, the row computes its canonical address, its mirrors and its place on this host. `browse.py` is an `App` that lists every location so and walks the addresses under its own key through gppufs. Run it with no arguments.
