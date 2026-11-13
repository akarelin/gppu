"""App construction receives the environment and selects its own configuration."""
from copy import deepcopy

import pytest

from gppu import App, Env, glob, glob_dict, jinja_template


@pytest.fixture(autouse=True)
def environment():
    previous, initialized, name = deepcopy(glob_dict('')), Env.initialized, Env.name
    Env.reset()
    yield
    Env.name = name
    App(environment=previous)
    if not initialized:
        Env.reset()


def test_declared_file_resolves_includes_from_its_directory(tmp_path, monkeypatch):
    configuration = tmp_path / 'environment'
    configuration.mkdir()
    (configuration / 'hosts.yaml').write_text('seven: {tags: [server]}\n', encoding='utf-8')
    entry = configuration / 'config.yaml'
    entry.write_text('hosts: !include hosts.yaml\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    App(environment=entry)
    assert Env.initialized
    assert glob('hosts/seven/tags') == ['server']


def test_app_section_is_its_own_configuration():
    source = {'shared': {'value': 42}, 'example': {'enabled': False, 'names': ['seven']}}
    class Example(App):
        pass

    app = Example(environment=source)
    source['example']['names'].append('trix')
    assert app.name == 'example'
    assert app.my('enabled') is False
    assert app.my('names') == ['seven']
    assert app.my('shared') is None
    assert glob('shared/value') == 42
    app.my('names').append('iot')
    assert app.my('names') == ['seven', 'iot']
    assert glob('example/names') == ['seven']


def test_missing_declared_file_raises_without_searching_or_replacing_environment(tmp_path):
    (tmp_path / 'config.yaml').write_text('wrong: true\n', encoding='utf-8')
    App(environment={'existing': True})
    with pytest.raises(FileNotFoundError):
        App(environment=tmp_path / 'missing.yaml')
    assert glob_dict('') == {'existing': True}


def test_reload_replaces_configuration_and_preserves_literal_strings():
    App(environment={'old': True})
    App(environment={'path': 'C:\\Users\\Alex\\"quoted"', 'shell': '$HOME ${missing}', 'empty': ''})
    assert glob('old') is None
    assert glob('path') == 'C:\\Users\\Alex\\"quoted"'
    assert glob('shell') == '$HOME ${missing}'
    assert glob('empty') == ''


def test_later_apps_share_the_environment_without_a_source():
    class First(App):
        pass

    class Second(App):
        pass

    first = First(environment={'first': {'value': 1}, 'second': {'value': 2}, 'shared': True})
    second = Second()
    assert first.my('value') == 1
    assert second.my('value') == 2
    assert glob('shared') is True


def test_first_app_requires_an_environment_declaration():
    with pytest.raises(ValueError, match='environment declaration'):
        App()


def test_fleet_node_templates_keep_booleans_and_omit_empty_conditional_keys():
    source = {'enabled': '{{ platform == "W11" }}', '{{ "windows" if platform == "W11" }}':
              {'items': ['{{ host }}', '', '123', False, 0]}}
    assert jinja_template(source, platform='W11', host='alex-pc') == {
        'enabled': True, 'windows': {'items': ['alex-pc', '', '123', False, 0]}}
    assert jinja_template(source, platform='Linux', host='seven') == {'enabled': False}
