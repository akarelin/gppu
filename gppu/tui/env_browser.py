"""Load gppu Env, validate its YAML tree, and browse Env.data as a navigable dict.

Usage::

    python -m gppu.tui.env_browser                  # load default Env, validate, open TUI
    python -m gppu.tui.env_browser --env IoT        # load IoT (_creekview.yaml)
    python -m gppu.tui.env_browser --env RAN        # load RAN (config.yaml)
    python -m gppu.tui.env_browser --validate       # validate and print summary without TUI
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml

from gppu.gppu import Env, Path, YmlLoader, dict_from_yml, full_path, jinja
from gppu.tui.config_editor import INCLUDE_RE, _LoaderWithInclude


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


@dataclass
class ValidationResult:
    environment: str
    config_path: Path
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


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
    result.data = Env.data
    if not result.data:
        result.errors.append('Env.data is empty after load')
    return result


def _preview(value: Any) -> str:
    if isinstance(value, dict):
        return f'dict ({len(value)})'
    if isinstance(value, list):
        return f'list ({len(value)})'
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + '...'


def _format_detail(path: str, value: Any) -> str:
    header = f'# {path or "<root>"}  ({type(value).__name__})\n'
    try:
        body = yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=100)
    except Exception:
        body = repr(value)
    return header + '\n' + body


from textual.app import App as TextualApp


class EnvBrowser(TextualApp):
    """Validate Env and display Env.data as a lazy-loaded navigable dict tree."""

    CSS = """
    #status { height: 3; padding: 0 1; background: $panel; content-align: left middle; }
    #filter { dock: top; margin: 0 1; }
    #body { height: 1fr; }
    #tree { width: 45%; border: round $primary; }
    #detail { width: 55%; border: round $secondary; padding: 0 1; }
    """

    BINDINGS = [
        ('q', 'quit', 'Quit'),
        ('r', 'reload', 'Reload'),
        ('e', 'switch_env', 'Switch RAN/IoT'),
        ('/', 'focus_filter', 'Filter'),
    ]

    def __init__(self, environment: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._target_env = environment
        self._result = validate_env(environment)

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Footer, Header, Input, Static, TextArea, Tree

        yield Header()
        yield Static('', id='status')
        yield Input(placeholder='Filter top-level keys (/ to focus, Esc to clear)...', id='filter')
        with Horizontal(id='body'):
            yield Tree(f'Env [{self._result.environment}]', id='tree')
            yield TextArea('', read_only=True, id='detail')
        yield Footer()

    def on_mount(self) -> None:
        from textual.widgets import Tree
        self._populate_tree()
        self.query_one('#tree', Tree).focus()

    def _populate_tree(self, needle: str = '') -> None:
        from textual.widgets import Static, TextArea, Tree

        res = self._result
        state = 'OK' if res.ok else f'{len(res.errors)} error(s)'
        warn = f', {len(res.warnings)} warning(s)' if res.warnings else ''
        self.query_one('#status', Static).update(
            f'Env: {res.environment}  |  {res.config_path}  |  {len(res.files)} files  |  {state}{warn}'
        )

        tree = self.query_one('#tree', Tree)
        tree.clear()
        tree.root.set_label(f'Env [{res.environment}] ({len(res.data)} keys)')
        tree.root.data = ('', res.data, True)
        self._add_children(tree.root, res.data, '', needle=needle.casefold())
        tree.root.expand()

        lines = [f'Environment: {res.environment}', f'Config: {res.config_path}', f'Files: {len(res.files)}']
        if res.errors:
            lines.append('\nErrors:')
            lines.extend(f'  - {e}' for e in res.errors)
        if res.warnings:
            lines.append('\nWarnings:')
            lines.extend(f'  - {w}' for w in res.warnings)
        self.query_one('#detail', TextArea).text = '\n'.join(lines)

    def _add_children(self, node, value: Any, prefix: str, needle: str = '') -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                key = str(k)
                if needle and not prefix and needle not in key.casefold():
                    continue
                child_path = f'{prefix}/{key}' if prefix else key
                is_branch = isinstance(v, (dict, list)) and bool(v)
                label = f'{key}: {_preview(v)}'
                if is_branch:
                    node.add(label, data=(child_path, v, False))
                else:
                    node.add_leaf(label, data=(child_path, v, True))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                child_path = f'{prefix}[{i}]'
                is_branch = isinstance(v, (dict, list)) and bool(v)
                label = f'[{i}]: {_preview(v)}'
                if is_branch:
                    node.add(label, data=(child_path, v, False))
                else:
                    node.add_leaf(label, data=(child_path, v, True))

    def on_tree_node_expanded(self, event) -> None:
        data = event.node.data
        if not data:
            return
        path, value, loaded = data
        if not loaded:
            self._add_children(event.node, value, path)
            event.node.data = (path, value, True)

    def on_tree_node_highlighted(self, event) -> None:
        from textual.widgets import TextArea

        data = event.node.data
        if not data:
            return
        path, value, _ = data
        self.query_one('#detail', TextArea).text = _format_detail(path, value)

    def on_input_changed(self, event) -> None:
        if event.input.id == 'filter':
            self._populate_tree(needle=event.value.strip())

    def action_focus_filter(self) -> None:
        from textual.widgets import Input

        self.query_one('#filter', Input).focus()

    def action_reload(self) -> None:
        self._result = validate_env(self._result.environment)
        self._populate_tree()

    def action_switch_env(self) -> None:
        envs = sorted(Env._ENV_PATHS)
        nxt = envs[(envs.index(self._result.environment) + 1) % len(envs)]
        self._result = validate_env(nxt)
        self._populate_tree()


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
