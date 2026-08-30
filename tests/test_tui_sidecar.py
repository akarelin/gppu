from __future__ import annotations

import sys
from pathlib import Path

import pytest

from gppu.tui import (
    inject_source, load_sidecar_registry, read_sidecar, sidecar_command,
)

SIDECAR = '''---
name: Cleaner
description: Move finished sessions
nav: Sessions
icon: X
modes:
  default:
    name: Dry run
  run:
    name: Move
    args: [--run]
---

Prose the loader ignores.
'''


@pytest.fixture
def utility(tmp_path: Path) -> Path:
    script = tmp_path / 'cleaner.py'
    script.write_text('PREVIEW = 140\nKEEP = "old"\n', encoding='utf-8')
    (tmp_path / 'cleaner.py.md').write_text(SIDECAR, encoding='utf-8')
    return script


def test_manifest_comes_from_the_sidecar_and_names_the_utility(utility: Path) -> None:
    manifest = read_sidecar(utility.with_name('cleaner.py.md'))

    assert manifest['name'] == 'Cleaner'
    assert manifest['nav'] == 'Sessions'
    assert manifest['script'] == str(utility)
    assert manifest['cwd'] == str(utility.parent)
    assert list(manifest['modes']) == ['default', 'run']
    assert 'tui' not in utility.read_text(encoding='utf-8')


def test_registry_orders_by_nav_then_name(tmp_path: Path, utility: Path) -> None:
    (tmp_path / 'map.cmd').write_text('rem\n', encoding='utf-8')
    (tmp_path / 'map.cmd.md').write_text(
        '---\nname: map\nnav: Windows\n---\n', encoding='utf-8')
    (tmp_path / 'ping.sh').write_text('HOST=one\n', encoding='utf-8')
    (tmp_path / 'ping.sh.md').write_text('---\nname: ping\n---\n', encoding='utf-8')

    apps = load_sidecar_registry(tmp_path)

    assert list(apps) == ['ping', 'cleaner', 'map']
    assert apps['map']['platform'] == ['W11']
    assert 'platform' not in apps['ping']


def test_a_sidecar_without_its_utility_is_an_error(tmp_path: Path) -> None:
    (tmp_path / 'gone.py.md').write_text('---\nname: gone\n---\n', encoding='utf-8')

    with pytest.raises(FileNotFoundError):
        load_sidecar_registry(tmp_path)


def test_an_unknown_manifest_key_is_an_error(tmp_path: Path, utility: Path) -> None:
    utility.with_name('cleaner.py.md').write_text(
        '---\nname: Cleaner\nargs: [--run]\n---\n', encoding='utf-8')

    with pytest.raises(ValueError, match='unknown manifest keys'):
        load_sidecar_registry(tmp_path)


def test_an_inline_mode_cannot_inject(tmp_path: Path, utility: Path) -> None:
    utility.with_name('cleaner.py.md').write_text(
        '---\nname: Cleaner\nmodes:\n  go:\n    inline: true\n'
        '    inject: {PREVIEW: 240}\n---\n', encoding='utf-8')

    with pytest.raises(ValueError, match='injection needs a subprocess'):
        load_sidecar_registry(tmp_path)


def test_commands_follow_the_utility_suffix(tmp_path: Path) -> None:
    assert sidecar_command(tmp_path / 'a.py') == [sys.executable, str(tmp_path / 'a.py')]

    with pytest.raises(ValueError, match='Unsupported utility type'):
        sidecar_command(tmp_path / 'a.pl')


def test_injection_replaces_an_assignment_in_a_copy(utility: Path) -> None:
    before = utility.read_bytes()

    injected = inject_source(utility, {'PREVIEW': 240, 'KEEP': 'new'})

    assert injected.parent == utility.parent
    assert injected.read_text(encoding='utf-8') == "PREVIEW = 240\nKEEP = 'new'\n"
    assert utility.read_bytes() == before


def test_injecting_an_unassigned_name_is_an_error(utility: Path) -> None:
    with pytest.raises(ValueError, match='no assignment to inject into'):
        inject_source(utility, {'MISSING': 1})


def test_injection_renders_each_language_literal(tmp_path: Path) -> None:
    powershell = tmp_path / 'a.ps1'
    powershell.write_text("$Root = 'x'\n$Deep = 1\n", encoding='utf-8')
    injected = inject_source(powershell, {'Root': "it's", 'Deep': True})
    assert injected.read_text(encoding='utf-8') == "$Root = 'it''s'\n$Deep = $true\n"

    batch = tmp_path / 'a.cmd'
    batch.write_text('set ROOT=x\n', encoding='utf-8')
    injected = inject_source(batch, {'ROOT': r'D:\one'})
    assert injected.read_text(encoding='utf-8') == 'set ROOT=D:\\one\n'
