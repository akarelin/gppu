---
fileClass: Document
created: "2026-09-06 0149"
updated: "2026-11-14 0300"
generated: { by: "Codex/GPT-6", at: "2026-09-06T01:49:00-07:00" }
---

gppu has two kinds of templates: Jinja, and the basic `$` template filled by `template_populate`. An app has no template engine of its own. YAML includes resolve through `Env`.

## The two calls

- **`render_template(template, values, **more)`** renders one template: the name of a named template (a `*_templates` block of the loaded configuration) or a Jinja string. It renders with native result types, so a mapping, a list, a number, a boolean or `None` keeps its type, and a missing input raises Jinja's `UndefinedError`.
- **`apply_template(node, templates)`** merges every row of `node` whose `template:` names one of `templates` over that template; the row wins. The template's Jinja that reads the row stays as written, for the app that renders it. Loading a configuration does this for every row, with the templates its `templates:` blocks declare; code calls it only for rows it builds itself, such as an Insteon keypad's buttons or a hub's shades.

```python
render_template("{{ {'state': state, 'brightness': brightness} }}", state='on', brightness=0)
```

`jinja_template(node, **values)` renders every Jinja string of a node, keys included, for code that renders a whole mapping at once (the lake's naming, configure-all, harness).

## gppu's Jinja

`jinja` is the one Jinja environment gppu renders with: sandboxed, native, strict about missing inputs, with gppu's conversion and formatting helpers, Python's `dict`, `list`, `int`, `str` and the like, and `re`. Loading a configuration adds every `macros:` block and every named template to it, so a macro is callable by its name from any template.

Templates that include one another by their own names, such as a Container's naming templates or the lake's Markdown pages, render from an overlay of it over their mapping: `jinja.overlay(loader=DictLoader(templates)).get_template(name).render(values)`. The overlay has the same globals and helpers; only the names it finds are its own.

## Documents

A configuration document is a different matter. `JinjaDocument` renders text rather than native values, because a macro that writes `"seven"` would otherwise have its quotes evaluated away and the YAML it was building would stop being YAML. It loads templates from the directory its document sits in, so a document can `{% import %}` macros and read the facts it applies them to with `from_yaml`; `to_yaml` writes a value back out.

## Resolving rows

Alex, 2026-09-16: "Templates are generating dicts that are used to create objects. Startup/restart only. Templates are used to override class property behavior. Mostly by returning a value using jinja for calculations (regex matching of filenames in handlers). Templates can be stacked and applied in order. Templates have all needed to understand what they do in the same file."

Loading merges a row over the one template it names (`apply_template`). The file catalog stacks templates, a row naming a list applied in order, each with `apply_template`, and renders their Jinja with the row. The lake's stored configuration stacks them too and declares what its rows reference with `refs`; the lake resolves those tables itself (`graph_configuration.resolve_row`), with gppu's Jinja.
