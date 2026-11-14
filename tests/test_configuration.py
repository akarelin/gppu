"""An app declares its environment, RAN or IoT; Env loads it once. An app given its own configuration file reads that, independent from the environment; one given none reads its own section of the environment."""
import pytest

from gppu import App, Env, Logger, OSType, glob, jinja_template


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """RAN and IoT in a temporary home, which Env reads as on a host that is not Windows."""
    hosts = tmp_path / 'RAN' / '_config'
    hosts.mkdir(parents=True)
    (hosts / 'config.yaml').write_text(
        'fixture_hosts: !include rows.yaml\nexample: {enabled: false, names: [seven]}\nsecond: {value: 2}\n',
        encoding='utf-8')
    (hosts / 'rows.yaml').write_text('fixture-row: {tags: [fixture]}\n', encoding='utf-8')
    creekview = tmp_path / 'IoT' / '_Creekview'
    creekview.mkdir(parents=True)
    (creekview / '_creekview.yaml').write_text('fixture_creekview: true\n', encoding='utf-8')
    monkeypatch.setattr('gppu.gppu.detect_os', lambda: OSType.LINUX)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    Env.reset()
    yield tmp_path
    Env.reset()


class Example(App):
    pass


def test_app_with_an_environment_loads_it_first():
    app = Example(environment='RAN')
    assert Env.initialized
    assert glob('fixture_hosts/fixture-row/tags') == ['fixture']
    assert app.name == 'example'
    assert app.my('enabled') is False
    assert app.my('fixture_hosts') is None


def test_iot_reads_creekview():
    App(environment='IoT')
    assert glob('fixture_creekview') is True


def test_app_without_an_environment_starts_with_no_configuration():
    app = Example()
    assert not Env.initialized
    assert app.my('enabled') is None
    assert glob('example') is None
    assert Env.os is OSType.LINUX and Env.host and Env.user


def test_later_apps_share_the_loaded_environment():
    class Second(App):
        pass

    Example(environment='RAN')
    assert Second().my('value') == 2
    App(environment='IoT')
    assert glob('fixture_creekview') is None


def test_the_section_is_the_apps_own_copy():
    app = Example(environment='RAN')
    app.my('names').append('iot')
    assert app.my('names') == ['seven', 'iot']
    assert glob('example/names') == ['seven']


def test_the_command_line_goes_over_the_apps_own_configuration_not_the_environment():
    app = Example(environment='RAN', argv=['--enabled', 'yes', 'positional', '--cells', '--step/name', 'TechHit'])
    assert app.my('enabled') == 'yes'
    assert app.my('cells') is True
    assert app.my('step/name') == 'TechHit'
    assert app.my('names') == ['seven']
    assert glob('example/enabled') is False
    assert glob('cells') is None


def test_an_app_without_an_environment_takes_the_command_line():
    assert Example(argv=['--local', '--preview', '80']).my('') == {'local': True, 'preview': '80'}


def test_reset_lets_the_next_app_load_another_environment():
    App(environment='RAN')
    Env.reset()
    App(environment='IoT')
    assert glob('fixture_creekview') is True
    assert glob('example') is None


def test_unknown_environment_raises():
    with pytest.raises(ValueError, match='Unknown environment'):
        App(environment='Creekview')
    assert not Env.initialized


def test_missing_environment_file_raises(home):
    (home / 'IoT' / '_Creekview' / '_creekview.yaml').unlink()
    with pytest.raises(FileNotFoundError):
        App(environment='IoT')
    assert not Env.initialized


def test_async_init_sees_its_configuration_after_the_environment_loads():
    from gppu import AsyncApp

    class Example(AsyncApp):
        def init(self):
            self.seen = (self.my('enabled'), glob('second/value'))
            return super().init()

    assert Example(environment='RAN').seen == (False, 2)


def test_environment_applies_its_trace_rules(home):
    (home / 'RAN' / '_config' / 'config.yaml').write_text(
        'trace_rules: {all: true, Basic: false}\n', encoding='utf-8')
    previous = dict(Logger.trace_rules)
    try:
        App(environment='RAN')
        assert Logger.trace_rules == {'all': True, 'Basic': False}
    finally:
        Logger.init_logger(trace_rules=previous)


@pytest.mark.parametrize('value', ["''", 'true'])
def test_invalid_log_file_raises(home, value):
    (home / 'RAN' / '_config' / 'config.yaml').write_text(f'log_file: {value}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='explicit log_file'):
        App(environment='RAN')
    assert not Env.initialized


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
    assert not Env.initialized
    assert glob('') == {}


def test_own_configuration_is_independent_from_the_environment(home):
    own = home / 'example.yaml'
    own.write_text('enabled: true\n', encoding='utf-8')
    app = Example(environment='RAN', config=own)
    assert app.my('enabled') is True
    assert app.my('names') is None
    assert glob('example') == {'enabled': False, 'names': ['seven']}
    app.my_dict('').update(added=1)
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
    Example(environment='RAN')
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
    Example(environment='RAN')
    mounts = {'/mnt/S1/Public': '//s1/Public', '/mnt/S1/Lake': '//s1/Lake'}
    assert glob('seven') == mounts
    assert glob('trix') == {**mounts, '/mnt/S9/TulaCo-M365': '//s9/TulaCo\\040-\\040M365'}
    assert glob('next_port') == 4319


def test_own_configuration_fills_its_jinja_from_the_environment(home):
    (home / 'RAN' / '_config' / 'config.yaml').write_text('globals: {url: "https://otel"}\n', encoding='utf-8')
    own = home / 'example.yaml'
    own.write_text('''endpoint: "{{ glob('globals/url') }}/v1/traces"\n''', encoding='utf-8')
    assert Example(environment='RAN', config=own).my('endpoint') == 'https://otel/v1/traces'


def test_async_app_keeps_its_steps():
    from gppu import AsyncApp, YStepper

    assert AsyncApp.init is YStepper.init

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
            return super().start()

    import asyncio
    app = Example(environment='RAN')
    assert app.steps == ['init']
    asyncio.run(app.run())
    assert app.steps == ['init', 'init', 'load', 'start']
    assert app.initialized and app.loaded and app.started
