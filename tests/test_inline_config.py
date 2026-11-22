"""A script carries its configuration inline: the YAML assigned to MANIFEST within its first 4 kilobytes. An app given
the script as its configuration reads it there, and so does the launcher, which lists such a script as an item that
runs the script itself; the script is never run to read it."""
import pytest

from gppu import App, Env, dict_from_yml
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


def test_app_given_the_script_reads_its_manifest_without_running_it(tmp_path):
    class Example(App):
        pass

    app = Example(config=python_script(tmp_path))
    assert {key: app[key] for key in EXPECTED} == EXPECTED
    assert app.my('keep_hours') == 24
    assert app.my('manifest/name') == 'example'


def test_script_reads_as_its_yaml_file_would(tmp_path):
    (tmp_path / 'example.yaml').write_text(MANIFEST, encoding='utf-8')
    app = App(config=python_script(tmp_path))
    assert {key: app[key] for key in EXPECTED} == dict_from_yml(tmp_path / 'example.yaml')


def test_command_line_goes_over_the_manifest(tmp_path):
    assert App(config=str(python_script(tmp_path)), argv=['--keep_hours', '48']).my('keep_hours') == '48'


def test_raw_manifest_keeps_its_backslashes(tmp_path):
    script = tmp_path / 'raw.py'
    script.write_text('MANIFEST = r"""\n  folder: \'D:\\Work\'\n"""\n', encoding='utf-8')
    assert App(config=script).my('folder') == 'D:\\Work'


def test_script_without_a_manifest_assignment_raises(tmp_path):
    script = tmp_path / 'plain.py'
    script.write_text('"""A docstring."""\n\n"""\n  manifest: {name: bare}\n"""\nCONFIG = "manifest: {}"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no MANIFEST in its first 4 KB'):
        App(config=script)


def test_manifest_below_the_first_4_kb_is_not_read(tmp_path):
    script = tmp_path / 'late.py'
    script.write_text('#' * 4096 + '\nMANIFEST = """\n  manifest: {name: late}\n"""\n', encoding='utf-8')
    with pytest.raises(ValueError, match='no MANIFEST in its first 4 KB'):
        App(config=script)


@pytest.mark.parametrize('name, text', [
    ('mapper.cmd', 'goto :run\nMANIFEST = """\n  manifest:\n    name: mapper\n    platform: [W11]\n"""\n:run\nnet use\n'),
    ('tray-control.ps1', '<#\nMANIFEST = """\n  manifest:\n    name: tray-control\n"""\n#>\n\nStop-Process -Name explorer\n'),
])
def test_any_script_that_assigns_manifest_is_read_the_same_way(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding='utf-8')
    item = read_manifest(tmp_path, name)
    assert item['name'] == name.split('.')[0]
    assert item['script'] == str((tmp_path / name).resolve())


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
