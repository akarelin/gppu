"""A script carries its configuration inline: the YAML assigned to MANIFEST within its first 4 kilobytes. The launcher
reads it there and lists such a script as an item that runs the script itself; the script is never run to read it."""
from pathlib import Path

import pytest

from gppu import Env
pytest.importorskip('textual')   # .. the tui extra, which gppu.tui.launcher is built on
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
@pytest.fixture(autouse=True)
def reset():
    Env.data = {}   # .. no environment: each test's app reads what it is given


def python_script(folder, body=None):
    script = folder / 'example.py'
    script.write_text('"""An example utility."""\n\nimport sys\n\nMANIFEST = """' + (body or MANIFEST) + '"""\n\n'
                      'raise SystemExit("the script ran")\n', encoding='utf-8')
    return script


@pytest.mark.parametrize('name, text', [
    ('mapper.cmd', 'goto :run\nMANIFEST = """\n  manifest:\n    name: mapper\n    platform: [W11]\n"""\n:run\nnet use\n'),
    ('tray-control.ps1', '<#\nMANIFEST = """\n  manifest:\n    name: tray-control\n"""\n#>\n\nStop-Process -Name explorer\n'),
])
def test_any_script_that_assigns_manifest_is_read_the_same_way(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding='utf-8')
    item = read_manifest(tmp_path, name)
    assert item['name'] == name.split('.')[0]
    assert Path(item['script']) == (tmp_path / name).resolve()


def test_launcher_item_runs_the_script_that_carries_it(tmp_path):
    script = python_script(tmp_path)
    item = read_manifest(tmp_path, 'example.py')
    assert Path(item['script']) == script.resolve()
    assert Path(item['cwd']) == tmp_path.resolve()
    assert item['_config'] == {'archive': 'D:/SD.agents/claude.not', 'keep_hours': 24}


def test_launcher_item_keeps_the_script_it_names(tmp_path):
    (tmp_path / 'other.py').write_text('', encoding='utf-8')
    python_script(tmp_path, '\n  manifest:\n    name: example\n    script: other.py\n')
    assert Path(read_manifest(tmp_path, 'example.py')['script']) == (tmp_path / 'other.py').resolve()
