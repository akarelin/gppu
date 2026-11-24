"""An app reads its own section of the environment, with its own configuration file over it when it is given one; the app's copy is its own. The command line goes over both."""
import sys

import pytest

from gppu import App, AsyncApp, Env, dict_from_yml, glob, jinja, jinja_template


def environment(path):
    """New configuration for Env, as configuration that arrives after import is: one YAML load of the file, its Jinja filled."""
    Env.data = dict_from_yml(path)
    Env.data = jinja.configuration(Env.data)   # .. its Jinja reads glob, which reads what was loaded


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """RAN's configuration in a temporary folder, given to Env."""
    hosts = tmp_path / 'RAN' / '_config'
    hosts.mkdir(parents=True)
    (hosts / 'config.yaml').write_text(
        'fixture_hosts: !include rows.yaml\nexample: {enabled: false, names: [seven]}\nsecond: {value: 2}\n',
        encoding='utf-8')
    (hosts / 'rows.yaml').write_text('fixture-row: {tags: [fixture]}\n', encoding='utf-8')
    creekview = tmp_path / 'IoT' / '_Creekview'
    creekview.mkdir(parents=True)
    (creekview / '_creekview.yaml').write_text('fixture_creekview: true\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['example'])   # .. the command line is the test's own
    environment(hosts / 'config.yaml')
    return tmp_path


class Example(App):
    pass


def test_the_section_is_the_apps_own_copy():
    app = Example()
    app.my('names').append('iot')
    assert app.my('names') == ['seven', 'iot']
    assert glob('example/names') == ['seven']


def test_the_command_line_goes_over_the_apps_own_configuration_not_the_environment(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['example', '--enabled', 'yes', 'positional', '--cells', '--step/name', 'TechHit'])
    app = Example()
    assert app.my('enabled') is True   # .. a value is read as YAML, as configuration is
    assert app.my('cells') is True
    assert app.my('step/name') == 'TechHit'
    assert app.my('names') == ['seven']
    assert glob('example/enabled') is False
    assert glob('cells') is None


def test_an_app_takes_the_command_line(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['example', '--local', '--preview', '80'])
    app = Example()
    assert (app.my('local'), app.my('preview')) == (True, 80)   # .. a value is read as YAML, as configuration is


class Stepped(AsyncApp):
    def __init(self):   # .. its part of init: a private step, run after App's, which loaded the configuration
        self.seen = (self.my('enabled'), glob('second/value'))


def test_async_init_step_sees_its_configuration(home):
    (home / 'stepped.yaml').write_text('enabled: false\n', encoding='utf-8')
    assert Stepped(config=home / 'stepped.yaml').seen == (False, 2)


def test_fleet_node_templates_keep_booleans_and_omit_empty_conditional_keys():
    source = {'enabled': '{{ platform == "W11" }}', '{{ "windows" if platform == "W11" }}':
              {'items': ['{{ host }}', '', '123', False, 0]}}
    assert jinja_template(source, platform='W11', host='alex-pc') == {
        'enabled': True, 'windows': {'items': ['alex-pc', '', '123', False, 0]}}
    assert jinja_template(source, platform='Linux', host='seven') == {'enabled': False}


def test_app_loads_its_own_configuration_without_an_environment(home):
    own = home / 'example.yaml'
    own.write_text('mount_point: "G:"\nsources: !include sources.yaml\n', encoding='utf-8')
    (home / 'sources.yaml').write_text('Lake: //s1/Lake\n', encoding='utf-8')
    app = Example(config=own)
    assert app.my('mount_point') == 'G:'
    assert app.my('sources/Lake') == '//s1/Lake'
    assert app.my('names') == ['seven']   # .. its section of the environment, under its own file


def test_own_configuration_is_independent_from_the_environment(home):
    own = home / 'example.yaml'
    own.write_text('enabled: true\n', encoding='utf-8')
    app = Example(config=own)
    assert app.my('enabled') is True   # .. its own file over its section
    assert app.my('names') == ['seven']
    assert glob('example') == {'enabled': False, 'names': ['seven']}
    app.data.update(added=1)
    assert glob('example/added') is None


def test_missing_own_configuration_raises(home):
    with pytest.raises(FileNotFoundError):
        Example(config=home / 'missing.yaml')


def test_loading_keeps_literal_strings(home):
    own = home / 'example.yaml'
    own.write_text('path: \'C:\\Users\\Alex\\"quoted"\'\nshell: "$HOME ${missing}"\nempty: ""\n', encoding='utf-8')
    app = Example(config=own)
    assert app.my('path') == 'C:\\Users\\Alex\\"quoted"'
    assert app.my('shell') == '$HOME ${missing}'
    assert app.my('empty') == ''


def test_loading_fills_the_jinja_that_reads_only_glob(home):
    (home / 'RAN' / '_config' / 'config.yaml').write_text('''
globals: {url: "https://otel", port: 4318, mount: /mnt/S1}
shares: [Public, Lake]
endpoint: "{{ glob('globals/url') }}/v1/logs"
port: "{{ glob('globals/port') }}"
mounts: >-
  {%- set mounts = {} -%}
  {%- for share in glob('shares') -%}{%- set _ = mounts.update({glob('globals/mount') ~ '/' ~ share: '//s1/' ~ share}) -%}{%- endfor -%}
  {{- mounts -}}
copied: "{{ glob('mounts') }}"
bin: "{{ glob('globals/mount') }}/{{ platform }}"
"{{ 'windows' if platform == 'W11' }}": true
shell: 'export PATH="$HOME/.cargo/bin:$PATH"'
example: {enabled: false}
''', encoding='utf-8')
    environment(home / 'RAN' / '_config' / 'config.yaml')
    assert glob('endpoint') == 'https://otel/v1/logs'
    assert glob('port') == 4318
    assert glob('mounts') == {'/mnt/S1/Public': '//s1/Public', '/mnt/S1/Lake': '//s1/Lake'}
    assert glob('copied') == glob('mounts')
    assert glob('bin') == "{{ glob('globals/mount') }}/{{ platform }}"
    assert glob("{{ 'windows' if platform == 'W11' }}") is True
    assert glob('shell') == 'export PATH="$HOME/.cargo/bin:$PATH"'


def test_loading_fills_the_jinja_that_reads_the_typed_globs(home):
    (home / 'RAN' / '_config' / 'config.yaml').write_text('''
shares: [Public, Lake]
port: 4318
server_mounts: >-
  {%- set mounts = {} -%}
  {%- for share in glob_list('shares') -%}{%- set _ = mounts.update({'/mnt/S1/' ~ share: '//s1/' ~ share}) -%}{%- endfor -%}
  {{- mounts -}}
seven: "{{ glob_dict('server_mounts') }}"
trix: >-
  {{ dict(glob_dict('server_mounts'), **{'/mnt/S9/TulaCo-M365': '//s9/TulaCo\\\\040-\\\\040M365'}) }}
next_port: "{{ glob_int('port') + 1 }}"
''', encoding='utf-8')
    environment(home / 'RAN' / '_config' / 'config.yaml')
    mounts = {'/mnt/S1/Public': '//s1/Public', '/mnt/S1/Lake': '//s1/Lake'}
    assert glob('seven') == mounts
    assert glob('trix') == {**mounts, '/mnt/S9/TulaCo-M365': '//s9/TulaCo\\040-\\040M365'}
    assert glob('next_port') == 4319


def test_async_app_keeps_its_steps():
    from gppu import AsyncApp
    from gppu.gppu import YStart

    assert AsyncApp.init is YStart.init

    class Example(AsyncApp):
        steps = []

        def init(self):
            self.steps.append('init')
            return super().init()

        def load(self):
            self.steps.append('load')
            return super().load()

        def start(self):
            self.steps.append('start')
            result = super().start()
            self.stop()   # .. a started app runs until it is stopped
            return result

    import asyncio
    app = Example()
    assert app.steps == ['init']
    asyncio.run(app.run())
    assert app.steps == ['init', 'init', 'load', 'start']
    assert app.initialized and app.stopped
