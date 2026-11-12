<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/gppu.py c04882f239173b5f80535c0f71fe1565d9216034 -->
`gppu.gppu` is the core of gppu. It provides the program's configuration, its logging, and the path, URI, template, and conversion helpers that the other gppu modules use. Importing it starts a console log at once, so a program logs from its first line.

## How the parts work together

`Env` holds the program's configuration. It is one per program and global. `Env.from_env` loads a YAML file named after the program, or one you name, optionally merged over a topology file. `Env.init` loads the same configuration from `APP`, and command-line arguments of the form `--key value` override it. `Env.glob` reads a value at a slash path. Objects built on `_Base`, including `App`, copy that configuration and read it with `my`, `my_int`, `my_list`, and `my_dict`.

`Logger` writes the program's log. Its functions `Info`, `Debug`, `Warn`, and `Error` print coloured lines and apply trace rules. `Logger.enable_file_logging` mirrors the same lines to a rotating file. A class that mixes in `mixin_Logger` logs under its own name.

`Path` is a file system path that is also a `pathlib.Path`, and `full_path` resolves a user-supplied path, including mapping `/mnt/d/...` to `D:\...` on Windows. `probe_path` reports a file's attributes and the handler that should read it, without reading the file. `y2uri` holds a URI as a scheme, a path, a query, and a fragment.

`TemplateSet` compiles a configuration's Jinja. Startup templates generate the rows of a table and check that their references exist. Runtime templates are rendered later with `render_template`. `jinja_template` and `jinja_document` render Jinja directly, and `JinjaDocument` renders text documents without evaluating their quotes.

Data moves in and out through `dict_from_yml`, which follows `!include`, `dict_to_yml`, `dict_to_json`, and `dict_from_json`. `deepget` reads nested values by slash path. The formatters `format_size`, `format_duration`, `format_since`, and `pfy` produce readable text, and `sync` lets synchronous code call an async function.

## Using the module

A program names itself and its application folder, then reads its settings and writes to its log:

```python
from pathlib import Path
from gppu.gppu import Env, Info, glob

Env.from_env(name='my-tool', app_path=Path(__file__).parent)
Info('Broker', glob('mqtt/host'))
```
