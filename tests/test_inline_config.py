"""A script carries its configuration inline: a .py in the string its global MANIFEST is assigned, a .cmd in the ::
lines it opens with, a .ps1 in the .NOTES of the <# #> block it opens with. The launcher lists such a script as an
item that runs the script itself, and an app given the script reads the same configuration."""
import pytest

from gppu import App, Env, dict_from_yml
from gppu.gppu import inline_config
from gppu.tui.launcher import read_manifest

MANIFEST = """
  manifest:
    name: example
    icon: "\\U0001F4CB"
    modes:
      run:
        name: Run
        args: [--run]
  archive: D:/SD.agents/claude.not
  keep_hours: 24
"""
EXPECTED = {'manifest': {'name': 'example', 'icon': '📋', 'modes': {'run': {'name': 'Run', 'args': ['--run']}}},
            'archive': 'D:/SD.agents/claude.not', 'keep_hours': 24}


@pytest.fixture(autouse=True)
def reset():
    Env.reset()
    yield
    Env.reset()


def python_script(folder, body=None):
    script = folder / 'example.py'
    script.write_text('"""An example utility."""\n\nimport sys\n\nMANIFEST = """' + (body or MANIFEST) + '"""\n\n'
                      'raise SystemExit("the script ran")\n', encoding='utf-8')
    return script


def test_python_script_reads_its_manifest_global_without_running(tmp_path):
    assert dict_from_yml(python_script(tmp_path)) == EXPECTED


def test_python_script_reads_as_its_yaml_file_would(tmp_path):
    (tmp_path / 'example.yaml').write_text(MANIFEST.replace('\\\\', '\\'), encoding='utf-8')
    assert dict_from_yml(python_script(tmp_path)) == dict_from_yml(tmp_path / 'example.yaml')


def test_inline_config_includes_beside_the_script(tmp_path):
    (tmp_path / 'rules.yaml').write_text('- disk\n', encoding='utf-8')
    script = python_script(tmp_path, '\n  manifest: {name: example}\n  rules: !include rules.yaml\n')
    assert dict_from_yml(script)['rules'] == ['disk']


def test_python_script_without_manifest_raises(tmp_path):
    script = tmp_path / 'plain.py'
    script.write_text('"""A docstring."""\n\n"""\n  manifest: {name: bare}\n"""\nCONFIG = "manifest: {}"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no inline configuration'):
        inline_config(script)


def test_cmd_reads_only_the_lines_it_opens_with(tmp_path):
    script = tmp_path / 'mapper.cmd'
    script.write_text('::manifest:\n::  name: mapper\n::  platform: [W11]\n\nnet use \\\\yellow /u:admin secret\n'
                      '::later: not read\n', encoding='utf-8')
    assert inline_config(script) == 'manifest:\n  name: mapper\n  platform: [W11]\n'
    assert dict_from_yml(script) == {'manifest': {'name': 'mapper', 'platform': ['W11']}}


def test_ps1_reads_the_notes_of_its_opening_block(tmp_path):
    script = tmp_path / 'tray-control.ps1'
    script.write_text('<#\n.SYNOPSIS\n  Promote the icons\n.NOTES\n  manifest:\n    name: tray-control\n.EXAMPLE\n'
                      '  ./tray-control.ps1\n#>\n\nStop-Process -Name explorer\n', encoding='utf-8')
    assert dict_from_yml(script) == {'manifest': {'name': 'tray-control'}}


def test_script_without_its_opening_block_raises(tmp_path):
    cmd, ps1 = tmp_path / 'plain.cmd', tmp_path / 'plain.ps1'
    cmd.write_text('@echo off\n::manifest: {name: late}\n', encoding='utf-8')
    ps1.write_text('Write-Host hi\n<#\n.NOTES\n  manifest: {name: late}\n#>\n', encoding='utf-8')
    for script in (cmd, ps1):
        with pytest.raises(ValueError, match='no inline configuration'):
            inline_config(script)


def test_launcher_item_runs_the_script_that_carries_it(tmp_path):
    script = python_script(tmp_path)
    item = read_manifest(tmp_path, 'example.py')
    assert item['script'] == str(script.resolve())
    assert item['cwd'] == str(tmp_path.resolve())
    assert item['_config'] == {'archive': 'D:/SD.agents/claude.not', 'keep_hours': 24}


def test_launcher_item_keeps_the_script_it_names(tmp_path):
    (tmp_path / 'other.py').write_text('', encoding='utf-8')
    python_script(tmp_path, '\n  manifest:\n    name: example\n    script: other.py\n')
    assert read_manifest(tmp_path, 'example.py')['script'] == str((tmp_path / 'other.py').resolve())


def test_app_given_the_script_reads_its_inline_config(tmp_path):
    class Example(App):
        pass

    app = Example(config=python_script(tmp_path))
    assert app.my('keep_hours') == 24
    assert app.my('manifest/name') == 'example'
