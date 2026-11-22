# .. archived 2026-11-22: what gppu's reduction removed from tests/test_configuration.py, as it was last


# .. from gppu/v3.7.9
def test_async_init_sees_its_configuration_after_the_environment_loads():
    from gppu import AsyncApp

    class Example(AsyncApp):
        def init(self):
            self.seen = (self.my('enabled'), glob('second/value'))
            return super().init()

    assert Example(environment='RAN').seen == (False, 2)


# .. archived 2026-11-22 from tests/test_configuration.py: the tests of an app naming its environment, Env.initialized, Env.reset, an unknown or missing environment, log_file and trace rules applied as an environment loads; Env is made once as gppu is imported, and none of that is its

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
    assert Second(environment='RAN').my('value') == 2     # .. naming the loaded environment again is the same one


def test_an_app_naming_another_environment_raises():
    App(environment='RAN')
    with pytest.raises(ValueError, match="'RAN' is loaded; 'IoT' cannot load as well"):
        App(environment='IoT')
    assert glob('fixture_creekview') is None


def test_reset_lets_the_next_app_load_another_environment():
    App(environment='RAN')
    Env.reset()
    App(environment='IoT')
    assert glob('fixture_creekview') is True
    assert glob('example') is None


def test_unknown_environment_raises():
    with pytest.raises(KeyError):   # .. a name that is neither of the two environments
        App(environment='Creekview')
    assert not Env.initialized


def test_missing_environment_file_raises(home):
    (home / 'IoT' / '_Creekview' / '_creekview.yaml').unlink()
    with pytest.raises(FileNotFoundError):
        App(environment='IoT')
    assert not Env.initialized


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
