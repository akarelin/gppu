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

Alex, 2026-09-16: "Templates are generating dicts that are used to create objects. Startup/restart only. Templates are used to override class property behavior. Mostly by returning a value using jinja for calculations (regex matching of filenames in handlers). Templates can be stacked and applied in order. Templates have all needed to understand what they do in the same file."

`TemplateSet` compiles one table's `macros`, `generators` and `templates` once and
resolves a row against them. A row names the template it is an instance of — one name,
or a list applied in order — and carries only what differs:

    1. template = the named templates, in order          (rightmost wins)
    2. values   = template | row
    3. data     = generator(values) | template | row      (rightmost wins)
    4. each Jinja value of the template renders against data, in template order
    5. data     = data | behavior(data)

A template value written in Jinja renders against the merged row, so the template says
in one place what it computes; a value the row carries is data and is never rendered. A
value renders against what is settled, so a later value sees an earlier one, and a value
still to be rendered is not a name yet. A generator or a behavior is a named Jinja
template that returns an object, never text; a behavior runs after the merge, so it is
the only thing that can rewrite a key the row itself carries. A row un-inherits a key
its template carries by setting it to null. An unknown template fails the resolution.

```yaml
templates:
  location:
    kind: Location
    refs: {'smb/*': connections, 'local/*': [platforms, hosts]}
    uris: "{{ uris(uid) }}"
    local: "{{ place(uid, Environment.host, Environment.platform) or none }}"
  synced:
    tags: [synced]

sd-lake:
  name: SD.Lake
  template: [location, synced]
  smb/s1: SD.Lake
  sd/s1: SD.Lake
```

A `*_templates` block holds named templates that render later, written in the same
Jinja — the grammar of an address, the payload of a command — and a row names one:
`uri: graph`. A rule renders it with what it knows then,
`render_template(resources[scheme].uri, host=..., share=..., path=...)`. It is data until
rendered, so the strictness of a template value does not apply to it. The blocks belong
to the configuration as a whole, as Y2's do: a name is unique across it, and a rule of
one table may render a template another table declares.

A template declares what its rows reference with `refs`, field to table. A field's value
is a row of the table it names — one, each of a list, or each key of a mapping — and a
field written with `*` is a key pattern: every key of the row shaped `smb/<name>`
references a connection. A table is a mapping at a slash path of the context, or a list
of paths. A reference nothing answers fails the resolution naming row, field and value.

`Env.template_set(path)` builds one from a table of the loaded configuration, with the
root's macros and the rest of the configuration offered to every generator. `State`
([Environment and State](environment.md)) resolves every table this way at startup.
