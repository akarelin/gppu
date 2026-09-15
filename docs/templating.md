---
fileClass: Document
created: "2026-09-06 0149"
updated: "2026-09-15 2125"
generated: { by: "Codex/GPT-6", at: "2026-09-06T01:49:00-07:00" }
---

gppu supports `$` substitution and Jinja. YAML includes continue to resolve through `Env`.

`template_populate` and `dict_template_populate` perform `$` substitution. `jinja_template(source, **values)` renders Jinja with native result types, so command mappings, lists, numbers, booleans and `None` retain their types. Missing inputs raise Jinja's `UndefinedError`.

```python
jinja_template("{{ {'state': state, 'brightness': brightness} }}", state='on', brightness=0)
```

`JinjaEnvironment` combines Jinja's sandbox and native rendering. It supplies gppu's safe type conversion and text formatting helpers as Jinja globals and filters. Applications can add their own loader and domain helpers to this environment.

A configuration document is a different matter. `JinjaDocument` renders text rather than native values, because a macro that writes `"seven"` would otherwise have its quotes evaluated away and the YAML it was building would stop being YAML. It loads templates from the directory its document sits in, so a document can `{% import %}` macros and read the facts it applies them to with `from_yaml`; `to_yaml` writes a value back out.

`dict_from_yml` renders a `.j2` file through it before YAML parses it, whether that file is the configuration or something it `!include`s, and `Env._config_file` matches `<name>.yaml.j2`. A templated configuration therefore loads through `Env.from_env` with no change at the call site.

```yaml
# config.yaml.j2
{% import 'macros/hosts.j2' as h %}
{% set facts = 'facts/hosts.yaml' | from_yaml %}
hosts:
{% for name, host in facts.hosts.items() %}
{{ h.entry(name, host) }}
{% endfor %}
```

## Resolving rows

`TemplateSet` compiles one configuration's `macros`, `generators` and `templates` once
and resolves a row against them, which is how a configuration keeps its rows short:

    1. values = template data + row
    2. data   = generator(values) | template data | row   (rightmost wins)
    3. data   = data | behavior(data)

A row names the template it is an instance of and carries only what differs. A
generator computes what follows from the row and returns an object, never text. A
behavior runs after the merge, so it is the only thing that can rewrite a key the row
itself carries. A row un-inherits a key its template carries by setting it to null.

`Env.template_set(path)` builds one from a section of the loaded configuration, with
the rest of the configuration offered to every generator.

```python
templates = Env.template_set()
host = templates.resolve({'name': 'seven', **Env.glob_dict('hosts/Servers/seven')})
```

The `py_*` evaluator, generator and template registry have been removed. Y2 owns its named template loader and object construction rules; its downstream YAML uses Jinja expressions and statements in the existing template sections.
