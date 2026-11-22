"""Tests for the environment's log and mixin_Logger."""
import logging
import importlib
import io

import pytest
from gppu import Env, mixin_Logger
from gppu.gppu import Logger


class TestEnvLogging:
    def test_logger_has_methods(self):
        assert callable(Env.Debug)
        assert callable(Env.Info)
        assert callable(Env.Warn)
        assert callable(Env.Error)
        assert callable(Env.Dump)


class TestInitLogger:
    def test_the_log_calls_are_not_promoted(self):
        import gppu
        assert not {'init_logger', 'enable_file_logging', 'file_log'} & set(gppu.__all__)


class TestMixinLogger:
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

