---
fileClass: Document
created: "2026-09-06 0149"
updated: "2026-09-06 0149"
generated: { by: "Codex/GPT-6", at: "2026-09-06T01:49:00-07:00" }
---

gppu supports `$` substitution and Jinja. YAML includes continue to resolve through `Env`.

`template_populate` and `dict_template_populate` perform `$` substitution. `jinja_template(source, **values)` renders Jinja with native result types, so command mappings, lists, numbers, booleans and `None` retain their types. Missing inputs raise Jinja's `UndefinedError`.

```python
jinja_template("{{ {'state': state, 'brightness': brightness} }}", state='on', brightness=0)
```

`JinjaEnvironment` combines Jinja's sandbox and native rendering. It supplies gppu's safe type conversion and text formatting helpers as Jinja globals and filters. Applications can add their own loader and domain helpers to this environment.

The `py_*` evaluator, generator and template registry have been removed. Y2 owns its named template loader and object construction rules; its downstream YAML uses Jinja expressions and statements in the existing template sections.
