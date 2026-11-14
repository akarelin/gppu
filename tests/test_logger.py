"""Tests for the environment's log and mixin_Logger."""
import logging
import importlib
import io

import pytest
from gppu import TRACE_RULES
from gppu import Env, Logger, mixin_Logger


@pytest.fixture
def output(monkeypatch, tmp_path):
    core = importlib.import_module('gppu.gppu')
    previous_rules = dict(TRACE_RULES)
    console = io.StringIO()
    original = core.Logger._console.setStream(console)
    Logger.init_logger('logging-verification', trace_rules={'all': True})
    path = Logger.enable_file_logging('verification', log_dir=tmp_path)
    yield core, console, path
    core.Logger._console.setStream(original)
    for handler in tuple(core.Logger._file_handlers.values()):
        core.Logger._root.removeHandler(handler)
        handler.close()
    core.Logger._file_handlers.clear()
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
    core.Logger._logger.addHandler(handler)
    try:
        core.Info('WBLUE', 'message', 'NONE', 'value')
        core.Logger._logger.info('ordinary %s', 'message')
    finally:
        core.Logger._logger.removeHandler(handler)
    assert text.getvalue().splitlines() == ['message value', 'ordinary message']


def test_mixin_created_before_init_keeps_both_outputs(output):
    core, console, path = output

    class Component(mixin_Logger):
        def publish(self): self.Info('mixin message')

    Logger.init_logger('renamed-application')
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
    Logger.file_log('WBLUE', 'panel line')
    assert console.getvalue() == ''
    assert path.read_text().strip() == 'panel line'


class TestEnvLogging:
    def test_logger_has_methods(self):
        assert callable(Env.Debug)
        assert callable(Env.Info)
        assert callable(Env.Warn)
        assert callable(Env.Error)
        assert callable(Env.Dump)


class TestInitLogger:
    def test_init_sets_name(self):
        Logger.init_logger("test_app")
        # Should not raise

    def test_init_with_trace_rules(self):
        rules = {"debug": True, "MyClass": False}
        Logger.init_logger("test_app", trace_rules=rules)
        assert Logger.trace_rules == rules

    def test_the_log_calls_are_not_promoted(self):
        import gppu
        assert not {'init_logger', 'enable_file_logging', 'file_log'} & set(gppu.__all__)


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
  original = core.Logger._console.setStream(console)
  yield core, console
  Env.reset()
  for handler in core.Logger._file_handlers.values():   # the files the test's environment opened
    core.Logger._root.removeHandler(handler)
    handler.close()
  core.Logger._file_handlers.clear()
  core.Logger._console.setStream(original)
  TRACE_RULES.clear()
  TRACE_RULES.update(previous_rules)


def test_env_defaults_to_console_without_legacy_environment_paths(configured_output, tmp_path, monkeypatch, ran):
  core, console = configured_output
  monkeypatch.setenv('GPPU_APP_NAME', 'invented')
  monkeypatch.setenv('GPPU_LOG_DIR', str(tmp_path / 'invented'))
  ran('{}')
  core.Info('console message')
  core.Debug('hidden trace')
  assert 'console message' in console.getvalue()
  assert 'hidden trace' not in console.getvalue()
  assert not core.Logger._file_handlers
  assert not (tmp_path / 'invented').exists()


def test_one_line_yaml_enables_console_and_file(configured_output, tmp_path, ran):
  core, console = configured_output
  path = tmp_path / 'declared.log'
  ran(f'log_file: {path.as_posix()}\n')
  core.Info('both destinations')
  assert 'both destinations' in console.getvalue()
  assert path.read_text().strip() == 'both destinations'
  assert Logger.enable_file_logging(log_file=str(path)) == path
  core.Info('once')
  assert path.read_text().count('once') == 1


def test_one_line_trace_yaml_keeps_the_mapping(configured_output, ran):
  core, console = configured_output
  ran('trace_rules: {all: true, Component: false}\n')

  class Component:
    def publish(self): core.Debug('excluded trace')

  Component().publish()
  core.Debug('included trace')
  assert 'excluded trace' not in console.getvalue()
  assert 'included trace' in console.getvalue()
  assert Logger.trace_rules == {'all': True, 'Component': False}
  Logger.init_logger(trace_rules=Logger.trace_rules)
  assert Logger.trace_rules == {'all': True, 'Component': False}


@pytest.mark.parametrize('value', [None, '', True])
def test_file_logging_requires_a_real_path(configured_output, value, ran):
  with pytest.raises(ValueError, match='explicit log_file'):
    ran({'log_file': value})


def test_file_creation_failure_is_reported(configured_output, tmp_path, ran):
  parent = tmp_path / 'file'
  parent.write_text('not a directory')
  with pytest.raises(OSError):
    ran({'log_file': str(parent / 'app.log')})


def test_boolean_does_not_replace_rich_trace_rules(configured_output, ran):
  TRACE_RULES.update({'all': True})
  with pytest.raises(TypeError):
    ran({'trace_rules': True})
  assert TRACE_RULES == {'all': True}
