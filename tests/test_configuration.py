"""An app declares its environment, Hosts or IoT; Env loads it once, then the app reads its own section."""
import pytest

from gppu import App, Env, Logger, OSType, glob, jinja_template


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Hosts and IoT in a temporary home, which Env reads as on a host that is not Windows."""
    hosts = tmp_path / 'RAN' / 'Hosts' / '_config'
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
    app = Example(environment='Hosts')
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

    Example(environment='Hosts')
    assert Second().my('value') == 2
    App(environment='IoT')
    assert glob('fixture_creekview') is None


def test_the_section_is_the_apps_own_copy():
    app = Example(environment='Hosts')
    app.my('names').append('iot')
    assert app.my('names') == ['seven', 'iot']
    assert glob('example/names') == ['seven']


def test_reset_lets_the_next_app_load_another_environment():
    App(environment='Hosts')
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

    assert Example(environment='Hosts').seen == (False, 2)


def test_environment_applies_its_trace_rules(home):
    (home / 'RAN' / 'Hosts' / '_config' / 'config.yaml').write_text(
        'trace_rules: {all: true, Basic: false}\n', encoding='utf-8')
    previous = dict(Logger.trace_rules)
    try:
        App(environment='Hosts')
        assert Logger.trace_rules == {'all': True, 'Basic': False}
    finally:
        Logger.init_logger(trace_rules=previous)


@pytest.mark.parametrize('value', ["''", 'true'])
def test_invalid_log_file_raises(home, value):
    (home / 'RAN' / 'Hosts' / '_config' / 'config.yaml').write_text(f'log_file: {value}\n', encoding='utf-8')
    with pytest.raises(ValueError, match='explicit log_file'):
        App(environment='Hosts')
    assert not Env.initialized


def test_fleet_node_templates_keep_booleans_and_omit_empty_conditional_keys():
    source = {'enabled': '{{ platform == "W11" }}', '{{ "windows" if platform == "W11" }}':
              {'items': ['{{ host }}', '', '123', False, 0]}}
    assert jinja_template(source, platform='W11', host='alex-pc') == {
        'enabled': True, 'windows': {'items': ['alex-pc', '', '123', False, 0]}}
    assert jinja_template(source, platform='Linux', host='seven') == {'enabled': False}
