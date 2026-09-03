"""Sidecar manifests — expose an existing script as a launcher item.

A utility ``{name}.{ext}`` is registered by a sidecar ``{name}.{ext}.md`` placed
next to it.  The sidecar's YAML frontmatter is a launcher manifest; ``script:``
is implied by the sidecar's own filename, so the utility source is never edited.

    # sessions-clean.py.md
    ---
    name: sessions-clean
    description: Move finished sessions out of the harness roots
    nav: Sessions
    icon: 🧹
    platform: [W11]
    modes:
      default:
        name: Dry run
      run:
        name: Move the files
        args: [--run]
    ---

    Prose below the frontmatter is for a human reader and is ignored here.

Parameters reach the utility two ways:

- ``args`` / ``ask_for`` — passed on the command line.
- ``inject`` — written into a copy of the source before it runs, for a utility
  that has no command line.  The original file is never written to.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from gppu import Env

from .launcher import _tui_available, platform_ok, _platform_label

FRONTMATTER = re.compile(r'\A---\r?\n(?P<yaml>.*?)\r?\n---\s*?(?:\r?\n|\Z)', re.S)

MANIFEST_KEYS = frozenset({
    'cwd', 'description', 'icon', 'inject', 'key', 'modes', 'name', 'nav',
    'platform', 'url',
})
MODE_KEYS = frozenset({
    'args', 'ask_for', 'inject', 'inline', 'name', 'platform',
})

RUNTIME_SUFFIXES = frozenset({'.cmd', '.ps1', '.py', '.sh'})
DEFAULT_PLATFORM = {'.cmd': ['W11'], '.ps1': ['W11']}


# ── Manifests ────────────────────────────────────────────────────────────────

def read_sidecar(sidecar: Path) -> dict:
    """Read one ``{name}.{ext}.md`` sidecar into a launcher manifest."""
    utility = sidecar.with_suffix('')
    if utility.suffix.casefold() not in RUNTIME_SUFFIXES:
        raise ValueError(f'{sidecar}: not a utility sidecar name')
    if not utility.is_file():
        raise FileNotFoundError(f'{sidecar}: utility does not exist: {utility}')

    match = FRONTMATTER.match(sidecar.read_text(encoding='utf-8-sig'))
    if not match:
        raise ValueError(f'{sidecar}: no YAML frontmatter')
    manifest = yaml.safe_load(match.group('yaml'))
    if not isinstance(manifest, dict):
        raise ValueError(f'{sidecar}: frontmatter must be a mapping')

    unknown = set(manifest) - MANIFEST_KEYS
    if unknown:
        raise ValueError(f'{sidecar}: unknown manifest keys: {sorted(unknown)}')
    for mode_key, mode in (manifest.get('modes') or {}).items():
        unknown = set(mode or {}) - MODE_KEYS
        if unknown:
            raise ValueError(
                f'{sidecar}: unknown keys in mode {mode_key!r}: {sorted(unknown)}')
        if (mode or {}).get('inline') and _mode_injects(mode):
            raise ValueError(
                f'{sidecar}: mode {mode_key!r} is inline; injection needs a subprocess')

    manifest.setdefault('name', utility.stem)
    manifest.setdefault('script', str(utility))
    manifest.setdefault('cwd', str(utility.parent))
    if 'platform' not in manifest and utility.suffix.casefold() in DEFAULT_PLATFORM:
        manifest['platform'] = DEFAULT_PLATFORM[utility.suffix.casefold()]
    manifest['sidecar'] = str(sidecar)
    return manifest


def _mode_injects(mode: dict | None) -> bool:
    mode = mode or {}
    return bool(mode.get('inject')) or any(
        isinstance(field, dict) and field.get('inject')
        for field in (mode.get('ask_for') or [])
    )


def load_sidecar_registry(*directories: Path) -> dict[str, dict]:
    """Collect every ``{name}.{ext}.md`` sidecar found in ``directories``.

    Items are ordered by ``nav`` path, then by display name.
    """
    apps: dict[str, dict] = {}
    for directory in directories:
        if not directory.is_dir():
            raise FileNotFoundError(f'Utility directory does not exist: {directory}')
        for sidecar in sorted(directory.glob('*.*.md')):
            if sidecar.with_suffix('').suffix.casefold() not in RUNTIME_SUFFIXES:
                continue
            manifest = read_sidecar(sidecar)
            key = manifest.pop('key', sidecar.with_suffix('').stem)
            if key in apps:
                raise ValueError(f'{sidecar}: duplicate item key: {key}')
            apps[key] = manifest
    return dict(sorted(
        apps.items(),
        key=lambda item: (item[1].get('nav', ''), item[1]['name']),
    ))


# ── Runtimes ─────────────────────────────────────────────────────────────────

def sidecar_command(script: Path) -> list[str]:
    """Command that runs ``script`` under the interpreter its suffix names."""
    suffix = script.suffix.casefold()
    if suffix == '.py':
        return [sys.executable, str(script)]
    if suffix == '.ps1':
        pwsh = shutil.which('pwsh')
        if pwsh is None:
            raise FileNotFoundError('Required executable is not available: pwsh')
        return [pwsh, '-NoProfile', '-File', str(script)]
    if suffix == '.cmd':
        if 'COMSPEC' not in os.environ:
            raise RuntimeError('Required environment variable is not set: COMSPEC')
        return [os.environ['COMSPEC'], '/d', '/c', str(script)]
    if suffix == '.sh':
        bash = shutil.which('bash')
        if bash is None:
            raise FileNotFoundError('Required executable is not available: bash')
        return [bash, str(script)]
    raise ValueError(f'Unsupported utility type: {script.suffix}')


# ── Injection ────────────────────────────────────────────────────────────────

def _python_literal(value: object) -> str:
    return repr(value)


def _powershell_literal(value: object) -> str:
    if isinstance(value, bool):
        return '$true' if value else '$false'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _shell_literal(value: object) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "'\\''") + "'"


def _cmd_literal(value: object) -> str:
    return str(value)


INJECT = {
    '.py': (r'^(?P<lead>{name}\s*=\s*)\S.*$', _python_literal),
    '.ps1': (r'^(?P<lead>\${name}\s*=\s*)\S.*$', _powershell_literal),
    '.sh': (r'^(?P<lead>{name}=)\S.*$', _shell_literal),
    '.cmd': (r'^(?P<lead>\s*set\s+{name}=)\S.*$', _cmd_literal),
}


def inject_source(script: Path, values: Mapping[str, object]) -> Path:
    """Write a copy of ``script`` beside it with each named assignment replaced.

    The name must already be assigned at the top level of the source; a name
    with no assignment is an error, not a new definition.
    """
    suffix = script.suffix.casefold()
    if suffix not in INJECT:
        raise ValueError(f'Injection is not defined for {script.suffix} sources')
    pattern, literal = INJECT[suffix]
    text = script.read_text(encoding='utf-8-sig')
    for name, value in values.items():
        expression = re.compile(pattern.format(name=re.escape(str(name))), re.M)
        text, replaced = expression.subn(
            lambda match, value=value: match.group('lead') + literal(value),
            text,
            count=1,
        )
        if not replaced:
            raise ValueError(f'{script}: no assignment to inject into: {name}')
    injected = script.with_name(f'.{script.stem}.tui{script.suffix}')
    injected.write_text(text, encoding='utf-8')
    return injected


# ── Launching ────────────────────────────────────────────────────────────────

def run_sidecar(
    app: dict,
    extra_args: Sequence[str] = (),
    inject: Mapping[str, object] | None = None,
) -> int:
    """Run a registered utility, injecting constants first when any are given. An item with a url is a web interface:
    it is opened in the browser and nothing is run."""
    if url := app.get('url'):
        webbrowser.open(url)
        return 0
    script = Path(app['script'])
    values = {**(app.get('inject') or {}), **(inject or {})}
    injected = inject_source(script, values) if values else None
    environment = dict(os.environ)
    environment['PYTHONUTF8'] = '1'
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['GPPU_APP_NAME'] = script.stem
    try:
        return subprocess.run(
            [*sidecar_command(injected or script), *extra_args],
            cwd=app.get('cwd') or script.parent,
            env=environment,
        ).returncode
    finally:
        if injected is not None:
            injected.unlink(missing_ok=True)


def sidecar_main(
    apps: dict[str, dict],
    app_class: type,
    app_dir: Path,
    description: str,
) -> int:
    """Entry point for a container of sidecar-registered utilities."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('app', nargs='?', choices=list(apps))
    parser.add_argument('--list', action='store_true', help='List items and exit')
    parser.add_argument(
        'extra', nargs=argparse.REMAINDER, help='Arguments passed to the item')
    args = parser.parse_args()

    if args.list:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        for key, app in apps.items():
            restriction = '' if platform_ok(app) else f'  [{_platform_label(app)} only]'
            nav = f"{app['nav']}/" if app.get('nav') else ''
            print(f"  {app.get('icon', ' ')}  {key:20s} {nav}{app['name']}{restriction}")
        return 0

    if args.app:
        app = apps[args.app]
        if not platform_ok(app):
            print(
                f'{args.app!r} is restricted to {_platform_label(app)}; '
                f'current OS is {Env.os.name}',
                file=sys.stderr,
            )
            return 2
        return run_sidecar(app, args.extra or ())

    if not _tui_available():
        parser.error('No terminal is available; name an item to run it directly')

    while True:
        result = app_class(apps, app_dir).run()
        if not result:
            return 0
        run_sidecar(
            result['app'], result.get('args') or (), result.get('inject') or None)
