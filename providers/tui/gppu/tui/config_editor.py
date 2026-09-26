"""YAML config editor TUIApp with file tree, preview, and validation.

Discovers files via ``!include`` traversal from a root YAML config.
Works as a TUIApp (embedded in launcher or standalone) with CLI fallback.

Usage::

    from gppu.tui.config_editor import ConfigEditorApp

    # Standalone
    ConfigEditorApp.main(root_config=Path('config.yaml'))

    # Or from manifest (module/class)
    manifest:
      module: gppu.tui.config_editor
      class: ConfigEditorApp
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import yaml

INCLUDE_RE = re.compile(r"(?:^|:\s*)!include\s+(?P<path>[^#\n]+)")


class LoaderWithInclude(yaml.SafeLoader):
    """YAML loader that tolerates !include tags for syntax validation."""


def _load_include(loader: LoaderWithInclude, node: yaml.Node) -> str:
    return loader.construct_scalar(node)


LoaderWithInclude.add_constructor('!include', _load_include)


# ── File discovery ──────────────────────────────────────────────────────────

def find_direct_includes(yaml_path: Path) -> list[Path]:
    """Return include targets declared in *yaml_path*."""
    includes: list[Path] = []
    base_dir = yaml_path.parent
    for line in yaml_path.read_text(encoding='utf-8').splitlines():
        match = INCLUDE_RE.search(line)
        if not match:
            continue
        raw_path = match.group('path').strip().strip('"\'')
        include_path = Path(raw_path)
        if not include_path.is_absolute():
            include_path = (base_dir / include_path).resolve()
        includes.append(include_path)
    return includes


def walk_includes(root_yaml: Path) -> list[Path]:
    """Return *root_yaml* and all recursively included files (cycle-safe)."""
    ordered: list[Path] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        ordered.append(resolved)
        if not resolved.exists() or not resolved.is_file():
            return
        for include in find_direct_includes(resolved):
            visit(include)

    visit(root_yaml)
    return ordered


def extend_unique(ordered: list[Path], values: Iterable[Path]) -> None:
    """Append values preserving order and uniqueness."""
    seen = set(ordered)
    for value in values:
        resolved = value.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)


def collect_yaml_targets(
    root_config: Path,
    extra_dirs: list[Path] | None = None,
    extra_files: list[Path] | None = None,
) -> list[Path]:
    """Build editable file list from root config + optional extra directories/files."""
    files = walk_includes(root_config)
    for d in (extra_dirs or []):
        if d.exists() and d.is_dir():
            extend_unique(files, sorted(d.rglob('*.yaml')))
    extend_unique(files, extra_files or [])
    return files


# ── Validation ──────────────────────────────────────────────────────────────

def _normalize_bare_includes(content: str) -> str:
    normalized_lines: list[str] = []
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith('!include '):
            indent = raw_line[: len(raw_line) - len(raw_line.lstrip())]
            include_target = stripped.split(' ', 1)[1]
            normalized_lines.append(f'{indent}- !include {include_target}')
            continue
        normalized_lines.append(raw_line)
    return '\n'.join(normalized_lines)


def validate_yaml(path: Path) -> tuple[bool, str | None]:
    """Validate YAML syntax while tolerating !include tags."""
    try:
        content = path.read_text(encoding='utf-8')
    except OSError as exc:
        return False, f'Unable to read file: {exc}'
    try:
        yaml.load(_normalize_bare_includes(content), Loader=LoaderWithInclude)
    except yaml.YAMLError as exc:
        return False, str(exc)
    return True, None


# ── Editor ──────────────────────────────────────────────────────────────────

def pick_editor() -> str:
    """Pick terminal editor command."""
    editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    if editor:
        return editor
    for candidate in ('nano', 'vim', 'vi'):
        if subprocess.run(['which', candidate], capture_output=True).returncode == 0:
            return candidate
    return 'vi'


# ── TUI App ─────────────────────────────────────────────────────────────────

from .launcher import TUIApp, StatusHeader, _tui_available
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, RichLog, Static, TextArea, Tree


class ConfigEditorApp(TUIApp):
    """TUI config editor with file tree, YAML preview, and inline editing."""

    TITLE = 'Config Editor'

    CSS = """
    #content { height: 1fr; }
    #file-tree { width: 40; border-right: solid $primary; height: 1fr; }
    #right-panel { height: 1fr; }
    .panel-label {
        dock: top; height: 1; padding: 0 1;
        text-align: center; background: $boost;
    }
    #preview-log { height: 1fr; }
    #editor-area { height: 1fr; display: none; }
    #editor-area.visible { display: block; }
    #status-bar { dock: bottom; height: 1; padding: 0 1; background: $boost; }
    """

    BINDINGS = [
        Binding('escape', 'cancel_edit', 'Back', priority=True),
        Binding('q', 'quit', 'Quit'),
        Binding('enter', 'edit', 'Edit'),
        Binding('v', 'validate_all', 'Validate All'),
        Binding('r', 'refresh', 'Refresh'),
    ]

    def __init__(
        self,
        root_config: Path | None = None,
        extra_dirs: list[Path] | None = None,
        extra_files: list[Path] | None = None,
        project_root: Path | None = None,
    ):
        super().__init__()
        self._root_config = root_config or Path('config.yaml')
        self._extra_dirs = extra_dirs or []
        self._extra_files = extra_files or []
        self._project_root = project_root or self._root_config.parent
        self._files: list[Path] = []
        self._file_map: dict[str, Path] = {}
        self._editing: Path | None = None

    def compose(self) -> ComposeResult:
        yield StatusHeader()
        with Horizontal(id='content'):
            yield Tree('Files', id='file-tree')
            with Vertical(id='right-panel'):
                yield Static('Preview', id='right-label', classes='panel-label')
                yield RichLog(id='preview-log', highlight=True, markup=True, wrap=False)
                yield TextArea(id='editor-area', language='yaml', show_line_numbers=True, tab_behavior='indent')
        yield Static('', id='status-bar')
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        self._files = collect_yaml_targets(
            self._root_config, self._extra_dirs, self._extra_files,
        )
        tree = self.query_one('#file-tree', Tree)
        tree.clear()
        tree.root.expand()
        self._file_map.clear()

        groups: dict[str, list[tuple[str, Path]]] = {}
        for fp in self._files:
            try:
                rel = fp.relative_to(self._project_root)
            except ValueError:
                rel = fp
            parts = str(rel).replace('\\', '/').split('/')
            if len(parts) > 1:
                group = '/'.join(parts[:-1])
                name = parts[-1]
            else:
                group = '.'
                name = parts[0]
            groups.setdefault(group, []).append((name, fp))

        for group, items in groups.items():
            if group == '.':
                parent = tree.root
            else:
                parent = tree.root.add(f'\U0001f4c1 {group}')
                parent.expand()
            for name, fp in items:
                node_id = f'file:{fp}'
                self._file_map[node_id] = fp
                label = name if fp.exists() else f'{name} [missing]'
                parent.add_leaf(label, data=node_id)

        self.query_one('#status-bar', Static).update(
            f'{len(self._files)} files  |  Enter: edit  v: validate all  r: refresh  q: quit'
        )

    # ── Preview mode ────────────────────────────────────────────────────

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if self._editing:
            return
        node_id = event.node.data
        if not node_id or not node_id.startswith('file:'):
            return
        fp = self._file_map.get(node_id)
        if fp:
            self._show_preview(fp)

    def _show_preview(self, fp: Path) -> None:
        log = self.query_one('#preview-log', RichLog)
        log.clear()
        try:
            rel = fp.relative_to(self._project_root)
        except ValueError:
            rel = fp
        log.write(f'[bold]{rel}[/bold]')

        valid, error = validate_yaml(fp)
        if valid:
            log.write('[green]\u2713 Valid YAML[/green]')
        else:
            log.write(f'[red]\u2717 {error}[/red]')
        log.write('')

        if not fp.exists():
            log.write('[dim]File does not exist[/dim]')
            return

        try:
            content = fp.read_text(encoding='utf-8')
            for i, line in enumerate(content.splitlines()[:100], 1):
                log.write(f'[dim]{i:>4}[/dim]  {line.replace("[", "\\[")}')
            if content.count('\n') > 100:
                log.write(f'[dim]  ... ({content.count(chr(10))} total lines)[/dim]')
        except OSError as e:
            log.write(f'[red]Error reading: {e}[/red]')

        if fp.exists():
            includes = find_direct_includes(fp)
            if includes:
                log.write('')
                log.write('[bold]Includes:[/bold]')
                for inc in includes:
                    exists = '[green]\u2713[/green]' if inc.exists() else '[red]\u2717[/red]'
                    try:
                        r = inc.relative_to(self._project_root)
                    except ValueError:
                        r = inc
                    log.write(f'  {exists} {r}')

    # ── Edit mode ───────────────────────────────────────────────────────

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        self.action_edit()

    def action_edit(self) -> None:
        if self._editing:
            self._save_and_close()
            return

        tree = self.query_one('#file-tree', Tree)
        node = tree.cursor_node
        if not node or not node.data or not node.data.startswith('file:'):
            return
        fp = self._file_map.get(node.data)
        if not fp:
            return

        if not fp.exists():
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.touch()

        try:
            content = fp.read_text(encoding='utf-8')
        except OSError as e:
            self.query_one('#status-bar', Static).update(f'[red]Error: {e}[/red]')
            return

        self._editing = fp
        editor = self.query_one('#editor-area', TextArea)
        editor.load_text(content)
        editor.add_class('visible')
        self.query_one('#preview-log', RichLog).display = False
        try:
            rel = fp.relative_to(self._project_root)
        except ValueError:
            rel = fp
        self.query_one('#right-label', Static).update(f'Editing: {rel}  |  Esc: save & close')
        self.query_one('#status-bar', Static).update(
            f'Editing {fp.name}  |  Esc: save & close'
        )
        editor.focus()

    def _save_and_close(self) -> None:
        if not self._editing:
            return

        fp = self._editing
        editor = self.query_one('#editor-area', TextArea)
        content = editor.text

        try:
            fp.write_text(content, encoding='utf-8')
        except OSError as e:
            self.query_one('#status-bar', Static).update(f'[red]Save failed: {e}[/red]')
            return

        valid, error = validate_yaml(fp)
        status = self.query_one('#status-bar', Static)
        if valid:
            status.update(f'[green]\u2713 Saved {fp.name} \u2014 valid YAML[/green]')
        else:
            status.update(f'[red]\u2717 Saved {fp.name} \u2014 {error}[/red]')

        self._editing = None
        editor.remove_class('visible')
        self.query_one('#preview-log', RichLog).display = True
        self.query_one('#right-label', Static).update('Preview')
        self._show_preview(fp)
        self.query_one('#file-tree', Tree).focus()

    def action_cancel_edit(self) -> None:
        if self._editing:
            self._save_and_close()
        else:
            self.action_quit()

    # ── Validate all ────────────────────────────────────────────────────

    def action_validate_all(self) -> None:
        if self._editing:
            return
        log = self.query_one('#preview-log', RichLog)
        log.clear()
        log.write('[bold]Validating all files...[/bold]')
        log.write('')
        ok = fail = 0
        for fp in self._files:
            if not fp.exists():
                continue
            valid, error = validate_yaml(fp)
            try:
                rel = fp.relative_to(self._project_root)
            except ValueError:
                rel = fp
            if valid:
                log.write(f'  [green]\u2713[/green] {rel}')
                ok += 1
            else:
                log.write(f'  [red]\u2717[/red] {rel}: {error}')
                fail += 1
        log.write('')
        log.write(f'[bold]{ok} passed, {fail} failed[/bold]')

    def action_refresh(self) -> None:
        if not self._editing:
            self._refresh_tree()

    def cli(self):
        """CLI fallback — numbered file list with editor launch."""
        return _cli_editor(self._root_config, self._extra_dirs, self._extra_files, self._project_root)


# ── CLI fallback ────────────────────────────────────────────────────────────

def _cli_editor(
    root_config: Path,
    extra_dirs: list[Path] | None = None,
    extra_files: list[Path] | None = None,
    project_root: Path | None = None,
) -> int:
    files = collect_yaml_targets(root_config, extra_dirs, extra_files)
    project_root = project_root or root_config.parent
    editor = pick_editor()

    while True:
        print(f'\nConfig Editor')
        print('=' * 60)
        for i, fp in enumerate(files, 1):
            try:
                display = fp.relative_to(project_root)
            except ValueError:
                display = fp
            exists = '' if fp.exists() else ' [missing]'
            print(f'{i:>2}. {display}{exists}')
        print(' q. Quit')

        choice = input('\nSelect file to edit: ').strip().lower()
        if choice in {'q', 'quit', 'exit'}:
            return 0
        if not choice.isdigit():
            print('Please enter a number or q.')
            continue
        index = int(choice) - 1
        if index < 0 or index >= len(files):
            print('Selection out of range.')
            continue

        target = files[index]
        if not target.exists():
            create = input(f'{target} does not exist. Create it? [y/N]: ').strip().lower()
            if create not in {'y', 'yes'}:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()

        subprocess.call([editor, str(target)])
        valid, error = validate_yaml(target)
        if valid:
            print(f'\u2713 YAML validation passed: {target}')
        else:
            print(f'\u2717 YAML validation failed: {target}')
            print(error or 'Unknown parse error')
        files = collect_yaml_targets(root_config, extra_dirs, extra_files)
