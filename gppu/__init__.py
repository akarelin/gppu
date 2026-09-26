"""gppu — configuration, secrets, logging, utilities, and the kinds of application; needs only PyYAML and Jinja2.

Each submodule adds one area and its dependencies: gppu.fs (files and Locations), gppu.iot (devices, MQTT, the Y2
lifecycle), gppu.tui (terminal and web apps), gppu.data (databases and persistence), gppu.chrome (browser).
"""
from .gppu import *  # noqa: F401,F403  utilities, logging, Env, State, _Base, _DC
from .gppu import Env, State, Vault, VaultProvider, VaultProviderAzure, VaultProviderOSEnviron, _Base, _DC, _mixin, mixin_Config, mixin_Logger, glob, glob_int, glob_list, glob_dict
from .connections import Provider, connection
from .params import Param, parameters, schema
from .app import App, CliApp, AsyncApp, EventLoopBridge, YStepper, _YMRO, mixin_Rest, mixin_Stepper, run, run_loop

Environment = Env

# gppu 3 names from the submodules, imported when first used, so `import gppu` needs only PyYAML and Jinja2.
_SUBMODULE_NAMES = {
  'fs': ('Collection', 'Container', 'DataObject', 'FileSystem', 'Location'),
  'iot': ('HTTPControl', 'JSONHTTPControl', 'MqttApp', 'SerializedControl', 'y2eid', 'y2slug'),
}


def __getattr__(name: str):
  for module, names in _SUBMODULE_NAMES.items():
    if name in names:
      from importlib import import_module
      return getattr(import_module(f'.{module}', __name__), name)
  raise AttributeError(f"module 'gppu' has no attribute {name!r}")
