---
fileClass: Document
created: "2026-09-06 0229"
updated: "2026-09-06 0229"
generated: { by: "Codex/GPT-6", at: "2026-09-06T02:29:00-07:00" }
---

`Env.from_env()` configures gppu logging from the application's YAML. `Info`, `Warn`, `Error`, `Debug` and the logging mixins need no application handler setup.

Console is the default. Adding one `log_file` line with an explicit filename enables file logging alongside console logging. No directory or filename is inferred, and an empty or invalid value is a configuration error. Paths use gppu's `full_path` resolution. Removing or commenting out that line and reloading the configuration closes the previous file handler.

Trace configuration retains the existing `TRACE_RULES` / `Logger.trace_rules` mapping. Enable all tracing on one line:

```yaml
trace_rules: {all: true}
```

The mapping also accepts function, module, module/function, class and class/function rules, using the existing dotted names and matching semantics. Explicit exclusions continue to suppress their matching traces. The mapping can still be supplied through `init_logger(trace_rules=...)` or updated through `Logger.trace_rules`.

Destination selection lives in `gppu.py`: `_sh` is the colored stderr handler, and `enable_file_logging` attaches the plain file formatter. Both formatters share `_fmt`. Application stdout remains available for ordinary output. Files retain the existing rotation policy of 4,000,000 bytes and five backups; file creation errors propagate.

While a Textual TUI is running, its debug panel receives console logs and the stderr handler is suspended. File logging continues, with the same trace rules. Exiting the TUI restores stderr. `file_log` remains available for panel messages that should only be mirrored to the file.

Explicit `enable_file_logging(name, log_dir=...)` calls remain supported. Without `log_dir`, the function requires the configured `log_file`. The old environment-variable hooks and implicit cache-directory path have been removed.
