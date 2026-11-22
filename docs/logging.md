---
fileClass: Document
created: "2026-09-06 0229"
updated: "2026-09-06 0229"
generated: { by: "Codex/GPT-6", at: "2026-09-06T02:29:00-07:00" }
---

gppu has one log, `Logger`: the console, from the moment gppu is imported, before the environment or any configuration exists. `Info`, `Warn`, `Error`, `Debug` and `Dump` are its methods; a class that has `mixin_Logger` calls them as `self.Info(...)`, and a line names the class and method it came from. There is no file log and no named or child logger.

The environment's configuration adds only the trace rules, which `Logger.trace_rules` holds and which decide which `Debug` lines show. Enable all tracing on one line:

```yaml
trace_rules: {all: true}
```

The mapping also accepts function, module, module/function, class and class/function rules; an explicit exclusion suppresses its matching traces.

While a Textual TUI runs, its debug panel receives the log and the console handler is suspended; leaving the TUI restores it.

`Dump(name, data)` writes data as YAML into `Logger.trace_folder`. A dump that fails writes its error beside the file as `<file>_error.txt`, the one place an error is written instead of raised, since no logger may be available where it runs.
