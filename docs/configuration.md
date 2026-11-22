# Configuration

There are two environments: RAN, `RAN/_config/config.yaml`, and Creekview, `IoT/_Creekview/_creekview.yaml`, under `D:\Dev` on Windows and under the home folder elsewhere. `Env` loads one of them as gppu is imported; no app or script names it. A program in the IoT or y2 repository is Creekview's, and so is any host without RAN's repository, as Y2's containers are; every other program is RAN's. A host with neither file, as PC Control's PCs, starts with an empty `Env` and gets its configuration over MQTT. `glob(...)` reads the environment.

```python
from gppu import App, glob

class Example(App):
    mode: str

    def main(self):
        self.Info(self.mode, glob('hosts'))

Example().main()
```

An app reads its configuration inside itself, through its annotations: nothing outside an app reads it. The program's app takes the environment's configuration under its name (`Example` reads `example`), or the configuration it is given: `config=` a YAML file, or a script's `MANIFEST` text. The command line goes over it: `--key value` sets the key to the string, a slash path names a nested key, `--flag` with no value after it sets it to True. An app a runtime makes from its row takes that row and nothing else.

Env loads in its own steps: its init finds the machine (`host`, `os`, `user`, `home`) and the environment, its load is one YAML load of the file. A configuration given whole, from MQTT or Y2's `configure`, goes into `Env.data` and loads through the same load step.

`examples/basic.py` is the smallest app.

## Templates

`jinja_template(node, **values)` renders strings, lists and mappings, including mapping keys. Jinja expressions return native objects; plain strings keep their type. Empty rendered keys are omitted, supporting Fleet's conditional configuration keys. Missing Jinja inputs raise.

Loading applies templates: it fills every Jinja value, key or string, that reads only `glob`, `glob_int`, `glob_list` or `glob_dict`, and each of them there reads the environment already filled, so one filled value can read another. Hosts' `server_mounts` generates the S1 mounts from `locations`, and a server row's `mounts: "{{ glob_dict('server_mounts') }}"` reads them. Jinja that reads `host`, `platform`, `my` or any other name stays as written, so Fleet can render it with the selected host's values later. `$` text, such as a runbook's `$HOME`, stays as written.
