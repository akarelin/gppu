<!-- written by Claude Code (haiku) from docs/prompts/module.md 41eee7c201042b801b3c26aaf28b2d27d9f39fac and gppu/gppu.py 6f150a4367300647ff070a40600ebd2305cea965 -->
`gppu.gppu` is the core of gppu. It holds the program's configuration and logging, plus the helpers the other gppu modules build on: paths, URIs, nested dictionaries, YAML and JSON files, Jinja templates, time and size formatting, and colored console output.

## How the pieces work together

`Env` is the program's configuration, one per program, static and global. `Env.init()` builds it from `APP`, a dict the program sets at its start. `APP` names the program, names its configuration file (found by that name when not set), and says whether a topology file and the command line are used. `Env.from_argv` lets the command line set keys over the configuration with `--key value`. `glob`, `glob_int`, `glob_list` and `glob_dict` read it with slash paths.

`_Base` gives an object a log and a configuration: a copy of `Env`, read with `self.my(...)`. `App` is a data class built on `_Base` and `_DC`. Its constructor arguments become its data.

`Logger` holds the program's log. `Info`, `Warn`, `Error`, `Debug` and `Dump` write through it. Output is colored and filtered by `TRACE_RULES`, which come from the configuration's `trace_rules`. `Logger.enable_file_logging` mirrors lines to a rotating file, and the configuration's `log_file` does the same. `mixin_Logger` gives a class its own child logger.

`TemplateSet` compiles a configuration's Jinja macros, generators and templates once. A row names its template and carries only what differs. Startup resolution builds each row's data, and `render_template` renders named templates later, when code asks for them. `jinja_template` and `jinja_document` render Jinja for one value or for a whole text file.

`full_path` resolves a user-supplied path. `Path` is a file system path with segment operators. `y2uri` parses URIs. `probe_path` reports file attributes without reading contents. `deepget` and its typed variants read a slash path from a nested dict. `dict_from_yml` loads YAML and follows `!include`. The JSON and YAML writers and readers cover the other formats.

The rest are small helpers: `safe_int`, `safe_float`, `safe_list` and `safe_datetime` coerce values; `TimeSpan` models a time interval; `format_size`, `format_duration` and `format_since` format numbers for display; `pcp` and `dpcp` print colored text; `sync` calls an async function from synchronous code.

## Using it

A program sets its keys in `APP` before its first read of configuration. The first read loads the configuration from them:

```python
from gppu.gppu import APP, Info, glob

APP['name'] = 'mytool'           # the configuration is found by this name
port = glob('server/port')       # a slash path into the configuration
Info('Listening on', port)
```
