"""The environment and apps read declared configuration through the same public method."""
from copy import deepcopy

import pytest

from gppu import App, Env, glob, glob_dict, jinja_template


@pytest.fixture(autouse=True)
def environment():
    previous, initialized, name = deepcopy(glob_dict('')), Env.initialized, Env.name
    Env.reset()
    yield
    Env.name = name
    Env.configure(previous)
    if not initialized:
        Env.reset()


def test_declared_file_resolves_includes_from_its_directory(tmp_path, monkeypatch):
    configuration = tmp_path / 'environment'
    configuration.mkdir()
    (configuration / 'hosts.yaml').write_text('seven: {tags: [server]}\n', encoding='utf-8')
    entry = configuration / 'config.yaml'
    entry.write_text('hosts: !include hosts.yaml\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    Env.configure(entry)
    assert Env.initialized
    assert glob('hosts/seven/tags') == ['server']


def test_app_section_is_its_own_configuration():
    source = {'shared': {'value': 42}, 'example': {'enabled': False, 'names': ['seven']}}
    Env.configure(source)
    source['example']['names'].append('trix')
    app = App(name='example')
    assert app.my('enabled') is False
    assert app.my('names') == ['seven']
    assert app.my('shared') is None
    assert glob('shared/value') == 42
    app.configure({'names': ['iot']})
    assert app.my('names') == ['iot']
    assert glob('example/names') == ['seven']


def test_missing_declared_file_raises_without_searching_or_replacing_environment(tmp_path):
    (tmp_path / 'config.yaml').write_text('wrong: true\n', encoding='utf-8')
    Env.configure({'existing': True})
    with pytest.raises(FileNotFoundError):
        Env.configure(tmp_path / 'missing.yaml')
    assert glob_dict('') == {'existing': True}


def test_reload_replaces_configuration_and_preserves_literal_strings():
    Env.configure({'old': True})
    Env.configure({'path': 'C:\\Users\\Alex\\"quoted"', 'shell': '$HOME ${missing}', 'empty': ''})
    assert glob('old') is None
    assert glob('path') == 'C:\\Users\\Alex\\"quoted"'
    assert glob('shell') == '$HOME ${missing}'
    assert glob('empty') == ''


def test_fleet_node_templates_keep_booleans_and_omit_empty_conditional_keys():
    source = {'enabled': '{{ platform == "W11" }}', '{{ "windows" if platform == "W11" }}':
              {'items': ['{{ host }}', '', '123', False, 0]}}
    assert jinja_template(source, platform='W11', host='alex-pc') == {
        'enabled': True, 'windows': {'items': ['alex-pc', '', '123', False, 0]}}
    assert jinja_template(source, platform='Linux', host='seven') == {'enabled': False}
