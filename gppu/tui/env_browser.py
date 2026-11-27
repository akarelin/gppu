"""Load gppu Env, validate its YAML tree, and browse Env.data with gppu.tui.TreeTable.

Usage::

    python -m gppu.tui.env_browser                  # load default Env, validate, open TUI
    python -m gppu.tui.env_browser --env IoT        # load IoT (_creekview.yaml)
    python -m gppu.tui.env_browser --env RAN        # load RAN (config.yaml)
    python -m gppu.tui.env_browser --validate       # validate and print summary without TUI
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any

import yaml
from rich.text import Text
from textual.app import App as TextualApp

from gppu.gppu import Env, Path, dict_from_yml, full_path, jinja
from gppu.tui.config_editor import INCLUDE_RE, _LoaderWithInclude
from gppu.tui.tree import TreeEntry
from gppu.tui.tree_table import TreeTable, TreeTableColumn


def _walk_active_includes(root_yaml: Path) -> list[Path]:
    """Return root_yaml and all active (non-commented) recursively !include'd files."""
    ordered: list[Path] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = Path(path).resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        ordered.append(resolved)
        if not resolved.exists() or not resolved.is_file():
            return
        base_dir = resolved.parent
        for line in resolved.read_text(encoding='utf-8').splitlines():
            code = line.split('#', 1)[0]
            match = INCLUDE_RE.search(code)
            if not match:
                continue
            visit(full_path(match.group('path').strip().strip('"\''), base_dir))

    visit(root_yaml)
    return ordered


def _collect_sources(root_yaml: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Walk YAML AST across !include files to map logical path -> 'relfile:line' and template name -> path."""
    root_dir = Path(root_yaml).resolve().parent
    sources: dict[str, str] = {}
    template_paths: dict[str, str] = {}

    def rel(p: Path) -> str:
        try:
            return str(Path(p).resolve().relative_to(root_dir)).replace('\\', '/')
        except Exception:
            return Path(p).name

    def walk_node(node: yaml.Node | None, cur_file: Path, prefix: str) -> None:
        if node is None:
            return
        if isinstance(node, yaml.ScalarNode) and node.tag == '!include':
            target = full_path(node.value.strip(), cur_file.parent)
            if target.exists() and target.is_file():
                load_file(target, prefix)
            return
        if isinstance(node, yaml.MappingNode):
            for k_node, v_node in node.value:
                if k_node.tag == 'tag:yaml.org,2002:merge':
                    # YAML merge key (<<: *anchor): record inherited keys if not overridden
                    targets = v_node.value if isinstance(v_node, yaml.SequenceNode) else [v_node]
                    for t in targets:
                        if isinstance(t, yaml.MappingNode):
                            for mk, mv in t.value:
                                mkey = str(mk.value)
                                mpath = f'{prefix}/{mkey}' if prefix else mkey
                                if mpath not in sources:
                                    sources[mpath] = f'{rel(cur_file)}:{mk.start_mark.line + 1} (anchor)'
                                    walk_node(mv, cur_file, mpath)
                    continue
                key = str(k_node.value)
                child_path = f'{prefix}/{key}' if prefix else key
                sources[child_path] = f'{rel(cur_file)}:{k_node.start_mark.line + 1}'
                if key == 'templates' and isinstance(v_node, yaml.MappingNode):
                    for tk, _ in v_node.value:
                        tname = str(tk.value)
                        template_paths[tname] = f'{child_path}/{tname}'
                walk_node(v_node, cur_file, child_path)
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                child_path = f'{prefix}[{i}]'
                sources[child_path] = f'{rel(cur_file)}:{item.start_mark.line + 1}'
                walk_node(item, cur_file, child_path)

    def load_file(fpath: Path, prefix: str) -> None:
        try:
            node = yaml.compose(fpath.read_text(encoding='utf-8'), Loader=yaml.SafeLoader)
        except Exception:
            return
        if prefix not in sources:
            sources[prefix] = rel(fpath)
        walk_node(node, fpath, prefix)

    load_file(Path(root_yaml).resolve(), '')
    return sources, template_paths


@dataclass
class ValidationResult:
    environment: str
    config_path: Path
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    template_paths: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def resolve_source(self, path: str, values: dict[str, Any]) -> str:
        """Where the value at `path` came from: file:line, template:<name>, or Env."""
        if not path:
            return self.sources.get('', str(self.config_path.name))
        if path in self.sources:
            return self.sources[path]
        # Walk up ancestors to check if inherited from a `template:` merge
        parts = path.split('/')
        for i in range(len(parts) - 1, 0, -1):
            parent_path = '/'.join(parts[:i])
            parent_val = values.get(parent_path)
            if isinstance(parent_val, dict) and isinstance(tpl := parent_val.get('template'), str):
                tail = '/'.join(parts[i:])
                tpl_root = self.template_paths.get(tpl)
                if tpl_root:
                    tpl_src = self.sources.get(f'{tpl_root}/{tail}') or self.sources.get(tpl_root)
                    if tpl_src:
                        return f'tpl:{tpl} ({tpl_src})'
                return f'tpl:{tpl}'
        if '/' not in path and path in ('os', 'host', 'user', 'home', 'environment', 'name'):
            return 'Env (machine)'
        return ''


def _check_templates(raw: Any, declared: set[str], warnings: list[str], path: str = '') -> None:
    if isinstance(raw, dict):
        tpl = raw.get('template')
        if isinstance(tpl, str) and tpl not in declared:
            warnings.append(f'{path or "<root>"}: template {tpl!r} is not declared in any templates: block')
        for key, value in raw.items():
            if key == 'templates':
                continue
            _check_templates(value, declared, warnings, f'{path}/{key}' if path else str(key))
    elif isinstance(raw, list):
        for i, item in enumerate(raw):
            _check_templates(item, declared, warnings, f'{path}[{i}]')


def validate_env(environment: str | None = None) -> ValidationResult:
    """Load Env (optionally switching environment) and validate YAML syntax, includes, and template references."""
    if environment:
        if environment not in Env._ENV_PATHS:
            raise ValueError(f'Unknown environment {environment!r}; expected one of {sorted(Env._ENV_PATHS)}')
        Env.data = {}
        Env.initialized = False
        Env.environment = environment
        Env.init()
    elif not Env.initialized:
        Env.init()

    env_name = Env.environment
    config_path = Env.home / Env._ENV_PATHS[env_name]
    result = ValidationResult(environment=env_name, config_path=config_path)

    if not config_path.exists():
        result.errors.append(f'Config file not found: {config_path}')
        return result

    result.files = _walk_active_includes(config_path)
    for fpath in result.files:
        if not fpath.exists():
            result.errors.append(f'Missing !include target: {fpath}')
            continue
        try:
            yaml.load(fpath.read_text(encoding='utf-8'), Loader=_LoaderWithInclude)
        except yaml.YAMLError as exc:
            result.errors.append(f'YAML syntax error in {fpath}: {exc}')

    if result.errors:
        return result

    try:
        raw = dict_from_yml(config_path)
    except Exception as exc:
        result.errors.append(f'Failed to load {config_path}: {exc}')
        return result

    try:
        declared = set(jinja._templates_of(raw))
    except ValueError as exc:
        result.errors.append(str(exc))
        declared = set()

    _check_templates(raw, declared, result.warnings)
    result.sources, result.template_paths = _collect_sources(config_path)
    result.data = Env.data
    if not result.data:
        result.errors.append('Env.data is empty after load')
    return result


def _scalar_preview(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return ''
    text = str(value)
    return text if len(text) <= 44 else text[:41] + '...'


def _count_cell(value: Any) -> Text | str:
    if isinstance(value, (dict, list)):
        return Text(str(len(value)), style='dim', justify='right')
    return ''


def _short_source(source: str) -> Text | str:
    if not source:
        return ''
    if source.startswith('tpl:'):
        return Text(source.split(' ', 1)[0], style='cyan')
    if source.startswith('Env'):
        return Text('Env', style='magenta')
    return Text(source.rsplit('/', 1)[-1], style='dim')


def _format_detail(path: str, value: Any, source: str = '') -> str:
    lines: list[str] = []
    if path:
        lines.append(f'# {path}')
    if source:
        lines.append(f'# source: {source}')
    header = ('\n'.join(lines) + '\n\n') if lines else ''
    try:
        body = yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100)
    except Exception:
        body = repr(value)
    return header + body


class _EnvTreeAdapter:
    """TreeAdapter over Env.data: clean keys, right-aligned item counts, scalar previews, and source provenance."""

    def __init__(self, result: ValidationResult, needle: str = '', hide_templates: bool = False) -> None:
        self._result = result
        self._needle = needle.casefold()
        self._hide_templates = hide_templates
        self._values: dict[str, Any] = {'': result.data}

    def set_data(self, result: ValidationResult, needle: str = '', hide_templates: bool | None = None) -> None:
        self._result = result
        self._needle = needle.casefold()
        if hide_templates is not None:
            self._hide_templates = hide_templates
        self._values = {'': result.data}

    def value_of(self, entry_id: str) -> Any:
        return self._values.get(entry_id)

    def source_of(self, entry_id: str) -> str:
        return self._result.resolve_source(entry_id, self._values)

    def root(self) -> TreeEntry:
        data = self._result.data
        return TreeEntry(
            id='',
            label=self._result.environment,
            is_container=True,
            meta={'count': _count_cell(data), 'value': '', 'source': _short_source(self.source_of(''))},
        )

    def _is_hidden_template(self, key: str, value: Any) -> bool:
        if not self._hide_templates:
            return False
        if key == 'templates' and isinstance(value, dict):
            return True
        if key == 'template' and isinstance(value, str):
            return True
        return False

    def children(self, entry: TreeEntry) -> list[TreeEntry]:
        value = self._values.get(entry.id)
        rows: list[TreeEntry] = []
        if isinstance(value, dict):
            for k, v in value.items():
                key = str(k)
                if self._is_hidden_template(key, v):
                    continue
                if self._needle and not entry.id and self._needle not in key.casefold():
                    continue
                child_id = f'{entry.id}/{key}' if entry.id else key
                self._values[child_id] = v
                rows.append(TreeEntry(
                    id=child_id,
                    label=key,
                    is_container=isinstance(v, (dict, list)) and bool(v),
                    meta={
                        'count': _count_cell(v),
                        'value': _scalar_preview(v),
                        'source': _short_source(self.source_of(child_id)),
                    },
                ))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                child_id = f'{entry.id}[{i}]'
                self._values[child_id] = v
                label = str(v['name']) if isinstance(v, dict) and v.get('name') else f'[{i}]'
                rows.append(TreeEntry(
                    id=child_id,
                    label=label,
                    is_container=isinstance(v, (dict, list)) and bool(v),
                    meta={
                        'count': _count_cell(v),
                        'value': _scalar_preview(v),
                        'source': _short_source(self.source_of(child_id)),
                    },
                ))
        return rows


class EnvBrowser(TextualApp):
    """Validate Env and display Env.data in gppu.tui.TreeTable with source provenance."""

    CSS = """
    #status { height: 3; padding: 0 1; background: $panel; content-align: left middle; }
    #filter { dock: top; margin: 0 1; }
    #body { height: 1fr; }
    #tree { width: 60%; border: round $primary; }
    #detail { width: 40%; border: round $secondary; padding: 0 1; }
    """

    BINDINGS = [
        ('q', 'quit', 'Quit'),
        ('r', 'reload', 'Reload'),
        ('e', 'switch_env', 'Switch RAN/IoT'),
        ('t', 'toggle_templates', 'Hide/Show templates'),
        ('/', 'focus_filter', 'Filter'),
    ]

    def __init__(self, environment: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._result = validate_env(environment)
        self._hide_templates = False
        self._adapter = _EnvTreeAdapter(self._result, hide_templates=self._hide_templates)

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Footer, Header, Input, Static, TextArea

        yield Header()
        yield Static('', id='status')
        yield Input(placeholder='Filter top-level keys (/ to focus)...', id='filter')
        with Horizontal(id='body'):
            yield TreeTable(
                self._adapter,
                columns=(
                    TreeTableColumn('count', '#', width=6),
                    TreeTableColumn('source', 'Source', width=20),
                    TreeTableColumn('value', 'Value'),
                ),
                tree_label='Key',
                id='tree',
            )
            yield TextArea('', read_only=True, id='detail')
        yield Footer()

    def on_mount(self) -> None:
        from textual.widgets import DataTable
        self._refresh_status()
        self.query_one('#tree', TreeTable).query_one(DataTable).focus()

    def _refresh_status(self) -> None:
        from textual.widgets import Static, TextArea

        res = self._result
        state = 'OK' if res.ok else f'{len(res.errors)} error(s)'
        warn = f', {len(res.warnings)} warning(s)' if res.warnings else ''
        tpl_mode = 'hidden' if self._hide_templates else 'shown'
        self.query_one('#status', Static).update(
            f'Env: {res.environment}  |  {res.config_path}  |  {len(res.files)} files  |  {state}{warn}  |  templates: {tpl_mode}'
        )
        lines = [f'Environment: {res.environment}', f'Config: {res.config_path}', f'Files: {len(res.files)}']
        if res.errors:
            lines.append('\nErrors:')
            lines.extend(f'  - {e}' for e in res.errors)
        if res.warnings:
            lines.append('\nWarnings:')
            lines.extend(f'  - {w}' for w in res.warnings)
        self.query_one('#detail', TextArea).text = '\n'.join(lines)

    def _reload_tree(self, needle: str = '') -> None:
        self._adapter.set_data(self._result, needle=needle, hide_templates=self._hide_templates)
        self.query_one('#tree', TreeTable).reset()
        self._refresh_status()

    def on_tree_table_entry_highlighted(self, event: TreeTable.EntryHighlighted) -> None:
        from textual.widgets import TextArea

        val = self._adapter.value_of(event.entry.id)
        src = self._adapter.source_of(event.entry.id)
        self.query_one('#detail', TextArea).text = _format_detail(event.entry.id, val, src)

    def on_input_changed(self, event) -> None:
        if event.input.id == 'filter':
            self._reload_tree(needle=event.value.strip())

    def action_focus_filter(self) -> None:
        from textual.widgets import Input

        self.query_one('#filter', Input).focus()

    def action_toggle_templates(self) -> None:
        self._hide_templates = not self._hide_templates
        self._reload_tree()

    def action_reload(self) -> None:
        self._result = validate_env(self._result.environment)
        self._reload_tree()

    def action_switch_env(self) -> None:
        envs = sorted(Env._ENV_PATHS)
        nxt = envs[(envs.index(self._result.environment) + 1) % len(envs)]
        self._result = validate_env(nxt)
        self._reload_tree()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Load, validate, and browse gppu Env.')
    parser.add_argument('--env', choices=sorted(Env._ENV_PATHS), default=None, help='Environment to load (default: auto-detected)')
    parser.add_argument('--validate', action='store_true', help='Validate and print summary without launching TUI')
    args = parser.parse_args(argv)

    if args.validate:
        res = validate_env(args.env)
        status = 'OK' if res.ok else 'FAILED'
        print(f'Env [{res.environment}] {status}: {res.config_path} ({len(res.files)} files, {len(res.data)} top-level keys)')
        for err in res.errors:
            print(f'  ERROR: {err}')
        for warn in res.warnings:
            print(f'  WARN: {warn}')
        return 0 if res.ok else 1

    EnvBrowser(environment=args.env).run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
