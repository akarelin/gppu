"""Tests for Logger, init_logger, mixin_Logger."""
import logging
import importlib
import io

import pytest
from gppu import TRACE_RULES
from gppu import Env, Logger, init_logger, mixin_Logger


@pytest.fixture
def output(monkeypatch, tmp_path):
    core = importlib.import_module('gppu.gppu')
    previous_rules = dict(TRACE_RULES)
    console = io.StringIO()
    original = core._sh.setStream(console)
    init_logger('logging-verification', trace_rules={'all': True})
    path = core.enable_file_logging('verification', log_dir=tmp_path)
    yield core, console, path
    core._sh.setStream(original)
    for handler in tuple(core._file_handlers.values()):
        core._log_root.removeHandler(handler)
        handler.close()
    core._file_handlers.clear()
    TRACE_RULES.clear()
    TRACE_RULES.update(previous_rules)


def test_console_and_file_share_content_and_keep_real_caller(output):
    core, console, path = output
    core.Info('WBLUE', 'message', 'NONE', 'value')
    assert 'test_console_and_file_share_content_and_keep_real_caller' in console.getvalue()
    assert 'StreamHandler.format' not in console.getvalue()
    assert '\x1b[' in console.getvalue()
    assert path.read_text().strip() == 'message value'


def test_standard_handlers_accept_gppu_multiple_arguments(output):
    core, _, _ = output
    text = io.StringIO()
    handler = logging.StreamHandler(text)
    core._logger.addHandler(handler)
    try:
        core.Info('WBLUE', 'message', 'NONE', 'value')
        core._logger.info('ordinary %s', 'message')
    finally:
        core._logger.removeHandler(handler)
    assert text.getvalue().splitlines() == ['message value', 'ordinary message']


def test_mixin_created_before_init_keeps_both_outputs(output):
    core, console, path = output

    class Component(mixin_Logger):
        def publish(self): self.Info('mixin message')

    init_logger('renamed-application')
    Component().publish()
    assert console.getvalue().count('mixin message') == 1
    assert path.read_text().count('mixin message') == 1


def test_exception_is_present_in_both_destinations(output):
    core, console, path = output
    try:
        raise ValueError('failure evidence')
    except ValueError:
        core.Error('operation failed', exc_info=True)
    assert 'ValueError: failure evidence' in console.getvalue()
    assert 'ValueError: failure evidence' in path.read_text()


@pytest.mark.parametrize('excluded', [
    'publish', 'test_logger', 'test_logger.publish', 'Component', 'Component.publish',
])
def test_rich_trace_exclusions_are_preserved(output, excluded):
    core, console, path = output

    class Component:
        def publish(self): core.Debug('trace message')

    TRACE_RULES.clear()
    TRACE_RULES.update({'all': True, excluded: False})
    Component().publish()
    assert console.getvalue() == ''
    assert path.read_text() == ''
    TRACE_RULES[excluded] = True
    Component().publish()
    assert 'trace message' in console.getvalue()
    assert 'trace message' in path.read_text()


def test_file_only_messages_do_not_write_to_console(output):
    core, console, path = output
    core.file_log('WBLUE', 'panel line')
    assert console.getvalue() == ''
    assert path.read_text().strip() == 'panel line'


class TestLogger:
    def test_logger_has_methods(self):
        assert callable(Logger.Debug)
        assert callable(Logger.Info)
        assert callable(Logger.Warn)
        assert callable(Logger.Error)
        assert callable(Logger.Dump)


class TestInitLogger:
    def test_init_sets_name(self):
        init_logger("test_app")
        # Should not raise

    def test_init_with_trace_rules(self):
        rules = {"debug": True, "MyClass": False}
        init_logger("test_app", trace_rules=rules)
        assert Logger.trace_rules == rules

    def test_init_logger_importable_from_gppu(self):
        from gppu import init_logger as top_init_logger
        assert top_init_logger is init_logger

    def test_init_logger_in_all(self):
        import gppu
        assert 'init_logger' in gppu.__all__


class TestMixinLogger:
    def test_subclass_gets_logger(self):
        class MyComponent(mixin_Logger):
            pass

        assert hasattr(MyComponent, '_logger')
        assert isinstance(MyComponent._logger, logging.Logger)

    def test_subclass_has_log_methods(self):
        class MyComponent(mixin_Logger):
            pass

        assert callable(MyComponent.Debug)
        assert callable(MyComponent.Info)
        assert callable(MyComponent.Warn)
        assert callable(MyComponent.Error)

    def test_instance_has_log_methods(self):
        class MyComponent(mixin_Logger):
            pass

        obj = MyComponent()
        assert callable(obj.Debug)
        assert callable(obj.Info)


@pytest.fixture
def configured_output():
  core = importlib.import_module('gppu.gppu')
  previous_rules = dict(TRACE_RULES)
  Env.reset()
  TRACE_RULES.clear()
  console = io.StringIO()
  original = core._sh.setStream(console)
  yield core, console
  Env.reset()
  core._sh.setStream(original)
  TRACE_RULES.clear()
  TRACE_RULES.update(previous_rules)


def test_env_defaults_to_console_without_legacy_environment_paths(configured_output, tmp_path, monkeypatch):
  core, console = configured_output
  monkeypatch.setenv('GPPU_APP_NAME', 'invented')
  monkeypatch.setenv('GPPU_LOG_DIR', str(tmp_path / 'invented'))
  (tmp_path / 'config.yaml').write_text('{}')
  Env.from_env(name='console-only', app_path=tmp_path)
  core.Info('console message')
  core.Debug('hidden trace')
  assert 'console message' in console.getvalue()
  assert 'hidden trace' not in console.getvalue()
  assert not core._file_handlers
  assert not (tmp_path / 'invented').exists()


def test_one_line_yaml_enables_console_and_file(configured_output, tmp_path):
  core, console = configured_output
  path = tmp_path / 'declared.log'
  (tmp_path / 'config.yaml').write_text(f'log_file: {path.as_posix()}\n')
  Env.from_env(name='configured-app', app_path=tmp_path)
  core.Info('both destinations')
  assert 'both destinations' in console.getvalue()
  assert path.read_text().strip() == 'both destinations'
  assert core.enable_file_logging() == path
  core.Info('once')
  assert path.read_text().count('once') == 1


def test_one_line_trace_yaml_keeps_the_mapping(configured_output, tmp_path):
  core, console = configured_output
  (tmp_path / 'config.yaml').write_text('trace_rules: {all: true, Component: false}\n')
  Env.from_env(name='traced-app', app_path=tmp_path)

  class Component:
    def publish(self): core.Debug('excluded trace')

  Component().publish()
  core.Debug('included trace')
  assert 'excluded trace' not in console.getvalue()
  assert 'included trace' in console.getvalue()
  assert Logger.trace_rules == {'all': True, 'Component': False}
  init_logger(trace_rules=Logger.trace_rules)
  assert Logger.trace_rules == {'all': True, 'Component': False}


def test_reloading_env_closes_previous_file(configured_output, tmp_path):
  core, _ = configured_output
  first, second = tmp_path / 'first.log', tmp_path / 'second.log'
  Env.from_dict({'log_file': str(first)})
  core.Info('first message')
  Env.from_dict({'log_file': str(second)})
  core.Info('second message')
  Env.from_dict({})
  core.Info('console only')
  assert first.read_text().strip() == 'first message'
  assert second.read_text().strip() == 'second message'
  assert not core._file_handlers


@pytest.mark.parametrize('value', [None, '', True])
def test_file_logging_requires_a_real_path(configured_output, value):
  with pytest.raises(ValueError, match='explicit log_file'):
    Env.from_dict({'log_file': value})


def test_file_creation_failure_is_reported(configured_output, tmp_path):
  parent = tmp_path / 'file'
  parent.write_text('not a directory')
  with pytest.raises(OSError):
    Env.from_dict({'log_file': str(parent / 'app.log')})


def test_boolean_does_not_replace_rich_trace_rules(configured_output):
  with pytest.raises(TypeError, match='mapping'):
    Env.from_dict({'trace_rules': True})
