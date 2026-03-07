"""Tests for Logger, init_logger, mixin_Logger."""
import logging
from gppu import Logger, init_logger, mixin_Logger, TRACE_RULES


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
