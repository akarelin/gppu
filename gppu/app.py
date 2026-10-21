"""gppu.app — application bases and lifecycle.

Import ``App`` from gppu for a synchronous utility, ``AsyncApp`` for asyncio
work, or ``MqttApp`` for an MQTT service. For Textual, use ``gppu.tui.TUIApp``.

The separate YMRO (Y2 Method Resolution Order) init→load→start lifecycle walks
the MRO for ``__method``-named methods on every ancestor and calls them in order,
giving cooperative multi-inheritance without explicit ``super()`` chains. Subclasses can extend
the lifecycle by overriding ``POSSIBLE_STEPS``. These are stepper hooks;
``App`` and ``AsyncApp`` do not run them.

``AsyncApp`` is the conventional asyncio counterpart: construction runs a
synchronous ``setup()`` hook, and ``run()`` opens one ``TaskGroup`` before
calling ``start()``. Long-lived work is added with ``_spawn()``.

Env: the configuration. One global Env loads the app's configuration (`Env.from_env`), and
through its `!include` of the shared one, everything the fleet knows; with it the basic level that
needs no file: platform, host, user, home, os and the trace rules. Every object built on `_Config`
copies the configuration into its `_my` and reads it with `self.my(...)`.

CliApp's parameters: what an app's ``main`` asks for, read from its signature, as Windmill reads a script's ``main``.

    def main(self, since: str = '7d', dry_run: bool = False) -> dict:
      \"\"\"Archive what changed.

      Args:
        since: How far back to look.
      \"\"\"

Each parameter is a command-line option, ``--since 3d``, ``--dry-run``; a positional-only one is a positional
argument. A value comes from, in order: the command line, the app's configuration under the parameter's name, the
signature's default. Anything still missing is an error.

The same description serves the command line, ``schema`` (JSON Schema, for a form or a REST manifest) and a call
from another app. The first docstring line is the description; ``Args:`` lines are the help.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import inspect
import json
import logging
import re
import socket
import sys
import types
import typing
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from string import Template
from typing import Any, Literal, Optional, final

from . import gppu as _core   # _core._logger is rebound by init_logger
from .gppu import (TRACE_RULES, Debug, Dump, Error, Info, Logger, OSType, Warn, _DC, _Logger, _file_handlers,
                   _log_root, _mixin, deepget, deepget_dict, deepget_float, deepget_int, deepget_list, detect_os, dict_from_yml,
                   enable_file_logging, sync, y2path)

_MISSING = object()
_trace_mro = False


# region Env: the configuration
class Env:
  data: dict[str, Any] = {}
  initialized: bool = False

  name: str
  app_path: Path

  home: Path = Path.home()
  user: str = getpass.getuser()
  os: OSType = detect_os()
  platform: str = {OSType.W11: 'windows', OSType.WSL: 'wsl', OSType.LINUX: 'debian', OSType.MACOS: 'macos'}[os]   # the shared configuration's words
  host: str = socket.gethostname().split('.')[0].lower()

  _logger: logging.Logger

  @staticmethod
  def _load_dict(d: dict) -> None:
    s = json.dumps(d)
    data = json.loads(Template(s).safe_substitute())
    if not isinstance(data, dict): raise TypeError('configuration must be a mapping')
    if 'trace_rules' in data and not isinstance(data['trace_rules'], dict):
      raise TypeError('trace_rules must be a mapping')
    if 'log_file' in data and (not isinstance(data['log_file'], str) or not data['log_file'].strip()):
      raise ValueError('File logging requires an explicit log_file in configuration')
    if 'trace_rules' in Env.data and 'trace_rules' not in data: TRACE_RULES.clear()
    if Env.initialized or Env.data: Env.reset(); Logger.Info('INFO', 'Environment', 'WRED', 'reset()')
    Env.data = data
    Env.initialized = True
    if 'trace_rules' in Env.data:
      rules = Env.glob('trace_rules')
      if not isinstance(rules, dict): raise TypeError('trace_rules must be a mapping')
      TRACE_RULES.clear()
      TRACE_RULES.update(rules)
    if 'log_file' in Env.data: enable_file_logging(log_file=Env.data['log_file'])

  @staticmethod
  def reset() -> None:
    for handler in tuple(_file_handlers.values()):
      _log_root.removeHandler(handler)
      handler.close()
    _file_handlers.clear()
    Env.data = {}
    Env.initialized = False

  @staticmethod
  def glob(path: str | y2path, default=None) -> Any: return Env.data if path == '' else deepget(path, Env.data, default=default)
  @staticmethod
  def glob_int(path: str | y2path, default: int = 0) -> int: return deepget_int(path, Env.data, default=default)
  @staticmethod
  def glob_list(path: str | y2path, default=[]) -> list: return deepget_list(path, Env.data, default=default)
  @staticmethod
  def glob_dict(path: str | y2path, default={}) -> dict: return Env.data if path == '' else deepget_dict(path, Env.data, default=default)
  @staticmethod
  @sync
  async def dump():
    Dump('Env.data', Env.data)
    return await asyncio.sleep(0)  # Make it truly async

  @staticmethod
  def from_dict(d: dict) -> None:
    """Initialize Env from a dict. A ``topology`` key (a yaml path) is loaded as
    the base data; ``tunables`` (an inline dict) and the remaining keys override
    it — mirroring Y2's Environment loader. Without ``topology`` the dict itself
    is the data (back-compatible)."""
    config = dict(d)
    topology = config.pop('topology', None)
    tunables = config.pop('tunables', None)
    data = dict_from_yml(topology) if topology else {}
    if isinstance(tunables, dict): data.update(tunables)
    data.update(config)
    Env._load_dict(data)

  @staticmethod
  def from_env(name: Optional[str] = None, app_path: Optional[Path] = None) -> None:
    """Initialize Env from name + app_path, resolving config file and loading YAML."""
    import __main__
    Env._main_file = Path(getattr(__main__, '__file__', 'app')).resolve()
    Env._main_dir = Env._main_file.parent

    # Under PyInstaller __main__.__file__ resolves to __main__; use exe name instead
    if name:
      Env.name = name
    elif getattr(sys, 'frozen', False):
      Env.name = Path(sys.executable).stem
    else:
      Env.name = Env._main_file.stem
    Env.app_path = Env._resolve_app_path(app_path)
    Env.config_file = Env._config_file()

    Env._logger = _core._logger.getChild(Env.name)
    for attr_name, fn in (('Debug', Debug), ('Info', Info), ('Warn', Warn), ('Error', Error), ('Dump', Dump)):
      setattr(Env, attr_name, staticmethod(partial(fn, logger=Env._logger)))

    config_data = dict_from_yml(Env.config_file)
    Env.from_dict(config_data)   # resolves a `topology:` key if the config has one

  @staticmethod
  def _resolve_app_path(app_path: Optional[Path] = None) -> Path:
    if not app_path: return Env._main_dir
    if app_path.is_absolute(): return app_path
    # Walk up from script location to find the relative path
    parent = Env._main_dir
    while parent != parent.parent:
      candidate = parent / app_path
      if candidate.exists(): return candidate
      parent = parent.parent
    return Env._main_dir / app_path

  @staticmethod
  def _config_file() -> Path:
    """``<name>.yaml`` then ``config.yaml``, searched from ``app_path`` upward —
    so a service in a subdir (e.g. /app/brultech) finds the suite's /app/config.yaml.
    Each is matched as a Jinja document too, so a templated configuration is found
    with no change at the call site."""
    stem = Path(Env.name).with_suffix('.yaml').name
    names = (stem, f'{stem}.j2', 'config.yaml', 'config.yaml.j2')
    for parent in (Env.app_path, *Env.app_path.parents):
      for name in names:
        candidate = parent / name
        if candidate.exists(): return candidate
    raise FileNotFoundError(f"Config ({' or '.join(names)}) not found walking up from '{Env.app_path}'")

# Global aliases for Env.glob* methods
glob = Env.glob
glob_int = Env.glob_int
glob_list = Env.glob_list
glob_dict = Env.glob_dict
# endregion


# region Configuration mixins
class mixin_Config(_mixin):
  _my: dict[str, Any] = {}

  def _config_from_key(self, key: str) -> None: self._my.update(Env.glob_dict(key))
  def _config_copy(self, other: mixin_Config) -> None: self._my = dict(other._my)
  def _config_from_dict(self, d: dict) -> None: self._my = deepcopy(d)
  def _config_from_env(self) -> None: self._my = deepcopy(Env.data)

  def my(self, path: str | y2path, default=None) -> Any: return deepget(path, self._my, default=default)
  def my_int(self, path: str | y2path, default: int = 0) -> int: return deepget_int(path, self._my, default=default)
  def my_float(self, path: str | y2path, default: float = float('nan')) -> float: return deepget_float(path, self._my, default=default)
  def my_list(self, path: str | y2path, default: list = []) -> list: return deepget_list(path, self._my, default=default or [])
  def my_dict(self, path: str | y2path, default: dict = {}) -> dict: return deepget_dict(path, self._my, default=default or {})


class _Config(mixin_Config):
  _base_path: Path

  def __init__(self, **kw) -> None:
    super().__init__(**kw)
    if Env.initialized:
      self._config_from_env()
    self._base_path = Path('.')

  # def my_path(self, path) -> Path: return self._base_path / self.my(path)


class _Base(_Logger, _Config): pass
# endregion


# region Configuration keys
def is_table_key(name: str) -> bool:   # what a table holds beside its rows: its macros, its generators, its templates and
  return name in ('macros', 'generators', 'templates') or name.endswith('_templates')   # its named templates
# endregion


# region Parameters
_JSON_TYPES = {str: 'string', int: 'integer', float: 'number', bool: 'boolean', Path: 'string', dict: 'object', list: 'array'}
_ARG_LINE = re.compile(r'^\s+(\w+)(?:\s*\([^)]*\))?:\s*(.+)$')


@dataclass
class Param:
  name: str
  type: Any
  default: Any
  help: str
  positional: bool = False

  @property
  def required(self) -> bool: return self.default is _MISSING

  @property
  def option(self) -> str: return '--' + self.name.replace('_', '-')


def _unwrap(annotation: Any) -> Any:
  """``X | None`` is X: None is a default, not a type."""
  if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if len(args) == 1: return args[0]
  return annotation


def _help(fn: Callable) -> tuple[str, dict[str, str]]:
  doc = inspect.getdoc(fn) or ''
  lines = doc.splitlines()
  helps, inside = {}, False
  for line in lines:
    if line.strip() in ('Args:', 'Arguments:', 'Parameters:'): inside = True; continue
    if inside and (m := _ARG_LINE.match(line)): helps[m.group(1)] = m.group(2)
    elif inside and line and not line[0].isspace(): inside = False
  return (lines[0] if lines else ''), helps


def parameters(fn: Callable) -> list[Param]:
  hints = typing.get_type_hints(fn)
  _, helps = _help(fn)
  return [Param(name, _unwrap(hints.get(name, str)), _MISSING if p.default is p.empty else p.default, helps.get(name, ''),
                p.kind is p.POSITIONAL_ONLY)
          for name, p in inspect.signature(fn).parameters.items()
          if name not in ('self', 'cls') and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]


def convert(param: Param, value: Any) -> Any:
  """value as the parameter's type. A command line gives strings; configuration gives YAML types."""
  kind, origin = param.type, typing.get_origin(param.type)
  if value is None: return None
  if origin is Literal:
    if value not in typing.get_args(kind): raise ValueError(f'{param.name}: {value!r} is not one of {typing.get_args(kind)}')
    return value
  if origin is list or kind is list:
    items = value if isinstance(value, list) else [value]
    inner = (typing.get_args(kind) or (str,))[0]
    return [inner(v) for v in items]
  if kind is dict or origin is dict: return json.loads(value) if isinstance(value, str) else dict(value)
  if kind is bool and isinstance(value, str): return value.lower() in ('1', 'true', 'yes', 'on')
  return kind(value) if isinstance(kind, type) and not isinstance(value, kind) else value


def parser(fn: Callable, prog: str) -> argparse.ArgumentParser:
  description, _ = _help(fn)
  cli = argparse.ArgumentParser(prog=prog, description=description, argument_default=argparse.SUPPRESS)
  cli.add_argument('--schema', action='store_true', help='print the parameters as JSON Schema and exit')
  for p in parameters(fn):
    if p.positional:
      choices = typing.get_args(p.type) if typing.get_origin(p.type) is Literal else None
      cli.add_argument(p.name, nargs=None if p.required else '?', choices=choices, help=p.help)
    elif p.type is bool: cli.add_argument(p.option, dest=p.name, action=argparse.BooleanOptionalAction, help=p.help)
    elif typing.get_origin(p.type) is list or p.type is list: cli.add_argument(p.option, dest=p.name, nargs='*', help=p.help)
    elif typing.get_origin(p.type) is Literal: cli.add_argument(p.option, dest=p.name, choices=typing.get_args(p.type), help=p.help)
    else: cli.add_argument(p.option, dest=p.name, help=p.help)
  return cli


def resolve(fn: Callable, given: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
  """The keyword arguments for fn: given, else config under the parameter's name, else the default. Missing raises."""
  unknown = set(given) - {p.name for p in parameters(fn)}
  if unknown: raise TypeError(f'{fn.__qualname__}: no parameter {sorted(unknown)}')
  kwargs = {}
  for p in parameters(fn):
    if p.name in given: value = given[p.name]
    elif (found := deepget(p.name, dict(config), _MISSING)) is not _MISSING: value = found
    elif not p.required: value = p.default
    else: raise LookupError(f'{p.name}: required; pass {p.option} or set {p.name} in configuration')
    kwargs[p.name] = convert(p, value)
  return kwargs


def call(fn: Callable, kwargs: Mapping[str, Any]) -> Any:
  """fn with resolved arguments: the positional-only ones by position, the rest by name."""
  names = [p.name for p in parameters(fn) if p.positional]
  return fn(*(kwargs[name] for name in names), **{k: v for k, v in kwargs.items() if k not in names})


def schema(fn: Callable) -> dict:
  """The parameters as JSON Schema."""
  description, _ = _help(fn)
  props, required = {}, []
  for p in parameters(fn):
    if typing.get_origin(p.type) is Literal: prop = {'enum': list(typing.get_args(p.type))}
    else: prop = {'type': _JSON_TYPES.get(typing.get_origin(p.type) or p.type, 'string')}
    if p.help: prop['description'] = p.help
    if not p.required: prop['default'] = str(p.default) if isinstance(p.default, Path) else p.default
    else: required.append(p.name)
    props[p.name] = prop
  return {'type': 'object', 'description': description, 'properties': props, 'required': required}
# endregion


# region YMRO lifecycle
class _YMRO:
  POSSIBLE_STEPS = ['init', 'load', 'start', 'stop']

  @property
  def _trace_mro(self) -> bool:
    result = getattr(self, 'args', {}).get('trace_mro', False)
    global _trace_mro
    _trace_mro = result
    return result


  def print_ymro(self):
    Logger.Debug('BY', self.__class__.__qualname__)
    siblings = [c for c in reversed(self.__class__.__mro__) if c != _YMRO and issubclass(c, _YMRO)]
    step = 'init'
    for sibling in siblings:
      Logger.Debug('DG', f"  {sibling.__qualname__}")
      qname = f"{sibling.__qualname__}__{step}"
      if qname[0] != '_': qname = '_' + qname
      method = getattr(self, qname, None)
      if method:
        Logger.Debug('INFO', f"  {method.__qualname__}")
        initers = getattr(sibling, '_initers', [])
        for initer in initers: Logger.Debug('DIM', f"     {initer.__qualname__}")


  def _ymros(self):
    result = {}
    siblings = [c for c in reversed(self.__class__.__mro__) if c != _YMRO and issubclass(c, _YMRO)]
    for step in self.POSSIBLE_STEPS:
      result[step] = []
      for sibling in siblings:
        qname = f"{sibling.__qualname__}__{step}"
        if qname[0] != '_': qname = '_' + qname
        method = getattr(self, qname, None)
        if method: result[step].append(method)
    return result

  def _ymro(self, method: str) -> list: return self._ymros().get(method, [])

  def _callall(self, method, *a, **kw): [m(*a, **kw) for m in self._ymro(method)]


class _YInit(_YMRO):
  @abstractmethod
  def __init(self): pass

  @final
  def init(self):
    if self.initialized: return
    self._callall('init')
    self.initialized = True

  @property
  def initialized(self) -> bool: return getattr(self, '_initialized', False)
  @initialized.setter
  def initialized(self, value: bool): self._initialized = value


class _YLoad(_YInit):
  @abstractmethod
  def __load(self): pass

  @final
  def load(self):
    if self.loaded: return
    assert self.initialized
    self._callall('load')
    self.loaded = True

  @property
  def loaded(self) -> bool: return getattr(self, '_loaded', False)
  @loaded.setter
  def loaded(self, value: bool): self._loaded = value


class _YStart(_YLoad):
  @abstractmethod
  def __start(self): pass

  @final
  def start(self):
    if self.started: return
    self._callall('start')
    self.started = True

  @property
  def started(self) -> bool: return getattr(self, '_started', False)
  @started.setter
  def started(self, value: bool): self._started = value


  @final
  def stop(self):
    if self.stopped: return
    self._callall('stop')
    self.started = False
    self.stopped = True
    self.loaded = False


  @property
  def stopped(self) -> bool: return getattr(self, '_stopped', False)
  @stopped.setter
  def stopped(self, value: bool): self._stopped = value


YStepper = _YStart
class mixin_Stepper(YStepper, _mixin): pass
# endregion


# region App
class _App(_Base):
  """Base class with logging, configuration, and automatic Env discovery."""

  name: str = ''

  def __init__(self, name: str = '', **kw) -> None:
    app_file = Path(inspect.getfile(type(self))).resolve()
    self.name = name or app_file.stem
    if not Env.initialized:
      Env.from_env(name=self.name, app_path=app_file.parent)
    super().__init__(name=self.name, **kw)


class App(_App, _DC):
  """Synchronous utility: define an entry method and call it after construction.

  Read settings with ``self.my(...)``. Construction loads Env beside the subclass
  when Env is uninitialized; an already loaded Env is reused.

  Usage::

      from gppu import App
      class Hello(App):
        def main(self):
          self.Info('Hello world')
      Hello().main()
  """
  pass


class CliApp(App):
  """Runs ``main`` once; the command line gives its parameters (Parameters, above). What it returns is printed as JSON on
  stdout; logs go to stderr. A parameter the command line does not give comes from the app's table in the
  configuration, named after the app, or from the whole configuration when there is no such table.

  Usage::

      from gppu import CliApp
      class Archive(CliApp):
        def main(self, since: str = '7d', dry_run: bool = False) -> dict:
          '''Archive what changed.'''
      if __name__ == '__main__': Archive.cli()
  """

  def main(self, *a, **kw) -> Any: raise NotImplementedError(f'{type(self).__name__} defines no main')

  def params(self, **given: Any) -> dict[str, Any]:
    """main's keyword arguments: given, then configuration, then defaults."""
    table = Env.data.get(self.name)
    return resolve(self.main, given, table if isinstance(table, dict) else Env.data)

  def invoke(self, **given: Any) -> Any: return call(self.main, self.params(**given))

  @classmethod
  def cli(cls, argv: list[str] | None = None) -> Any:
    """Start from the command line; ``--schema`` prints the parameters instead."""
    app = cls()
    given = vars(parser(app.main, app.name).parse_args(argv))
    if given.pop('schema', False): return print(json.dumps(schema(app.main), indent=2))
    result = app.invoke(**given)
    if result is not None: print(json.dumps(result, indent=2, default=str))
    return result
# endregion


# region event-loop bridge
type AsyncSubmission[T] = Future[T] | asyncio.Task[T]


class EventLoopBridge:
  """Schedules coroutines on an externally owned loop; ``call`` blocks off-loop."""

  def schedule[T](self, coroutine: Coroutine[Any, Any, T], /) -> AsyncSubmission[T]:
    return self._schedule(self._get_loop(), coroutine)

  def submit[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> AsyncSubmission[T]:
    return self.schedule(function(*args, **kwargs))

  def call[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    loop = self._get_loop()
    if self._on_loop(loop): raise RuntimeError('cannot block the target event-loop thread')
    future = self._schedule(loop, function(*args, **kwargs))
    try: return future.result()
    except BaseException:
      if not future.done(): future.cancel()
      raise

  def on_loop(self) -> bool: return self._on_loop(self._get_loop())

  @staticmethod
  def _schedule[T](loop: asyncio.AbstractEventLoop, coroutine: Coroutine[Any, Any, T], /) -> AsyncSubmission[T]:
    try:
      if EventLoopBridge._on_loop(loop): return loop.create_task(coroutine)
      return asyncio.run_coroutine_threadsafe(coroutine, loop)
    except BaseException:
      coroutine.close()
      raise

  @staticmethod
  def _on_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try: return asyncio.get_running_loop() is loop
    except RuntimeError: return False

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    raise NotImplementedError
# endregion


# region REST surface
def _born(cls: type) -> str:
  """Where a class's source lives; a built-in has none."""
  try: return inspect.getsourcefile(cls) or ''
  except TypeError: return ''


class mixin_Rest:
  """Every public member of the application's own classes, over HTTP, and nothing
  declared. A field or property reads; a method is called with the JSON body as
  its keyword arguments; a synchronous method needing none answers a GET as well.
  A name is the application's when a class born under ``Env.app_path`` defines
  it — a base may define it too — and the private names and the lifecycle steps
  are the only exclusion.

  APIApp includes this mixin; a host with its own lifecycle can compose it
  before its application base, as Y2 does. Override ``rest_registries()`` with
  ``{registry: {key: object}}``; by default it contains the app itself. The HTTP
  host serves ``rest_manifest`` and binds ``rest_objects``, ``rest_read`` and
  awaited ``rest_call``, which return ``(payload, status)``. The host supplies
  the HTTP listener and JSON serialization.
  """
  REST_RESERVED = (*_YMRO.POSSIBLE_STEPS, 'initialize', 'terminate', 'setup', 'run')
  _rest_manifest: dict | None = None

  def rest_registries(self) -> dict[str, Mapping]:
    """name -> roster of live objects (key -> object); the host names its own."""
    return {'app': {getattr(self, 'name', 'app'): self}}

  def _rest_members(self, cls: type) -> dict[str, dict]:
    home, rows = str(Env.app_path), {}
    for name in dir(cls):
      if name[0] == '_' or name in self.REST_RESERVED: continue
      if not any(_born(c).startswith(home) for c in cls.__mro__ if name in c.__dict__): continue
      member = inspect.getattr_static(cls, name)
      fn = getattr(member, '__func__', member)
      if not inspect.isfunction(fn): rows[name] = {'kind': 'value'}; continue
      params = [p for n, p in inspect.signature(fn).parameters.items() if n not in ('self', 'cls')]
      needed = [p for p in params if p.default is p.empty and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]
      rows[name] = {'kind': 'method', 'async': inspect.iscoroutinefunction(fn), 'doc': (fn.__doc__ or '').split('\n')[0],
                    'args': {p.name: {'required': p.default is p.empty} for p in params if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)},
                    'free': any(p.kind is p.VAR_KEYWORD for p in params),
                    'read': not needed and not inspect.iscoroutinefunction(fn)}
    return rows

  @property
  def rest_manifest(self) -> dict:
    """The classes born under app_path and their members, walked once."""
    if self._rest_manifest is None:
      seen, stack = set(), [_mixin, _Base, _DC]
      while stack:
        cls = stack.pop()
        if cls not in seen: seen.add(cls); stack.extend(cls.__subclasses__())
      home = str(Env.app_path)
      classes = {c.__name__: {'members': self._rest_members(c)} for c in sorted(seen, key=lambda c: c.__name__) if _born(c).startswith(home)}
      self._rest_manifest = {'registries': list(self.rest_registries()), 'classes': {n: c for n, c in classes.items() if c['members']}}
    return self._rest_manifest

  def _rest_find(self, registry: str, key: str):
    return next((o for k, o in (self.rest_registries().get(registry) or {}).items() if str(k) == key), None)

  def _rest_rows(self, obj) -> dict[str, dict]:
    return self.rest_manifest['classes'].get(type(obj).__name__, {}).get('members', {})

  def rest_payload(self, obj) -> dict:
    """What the object holds and what it can be asked to do. Values only are read
    here: calling a method to build a payload would run it for anyone listing the objects."""
    rows = self._rest_rows(obj)
    return {'class': type(obj).__name__,
            'members': {n: getattr(obj, n) for n, r in rows.items() if r['kind'] == 'value'},
            'methods': {n: r['args'] for n, r in rows.items() if r['kind'] == 'method'}}

  def rest_objects(self, kind: str | None = None, full: bool = False) -> tuple[dict, int]:
    out = {f'{registry}/{key}': self.rest_payload(obj) if full else type(obj).__name__
           for registry, roster in self.rest_registries().items() for key, obj in roster.items()
           if not kind or type(obj).__name__ == kind}
    return {'objects': out}, 200

  def rest_read(self, registry: str, key: str, name: str | None = None) -> tuple[dict, int]:
    obj = self._rest_find(registry, key)
    if obj is None: return {'success': False, 'error': 'no such object'}, 404
    if name is None: return self.rest_payload(obj), 200
    row = self._rest_rows(obj).get(name)
    if row is None: return {'success': False, 'error': f'{type(obj).__name__} has no {name!r}'}, 404
    if row['kind'] == 'method' and not row['read']: return {'success': False, 'error': f'{name} takes arguments; POST it'}, 405
    member = getattr(obj, name)
    return {name: member() if row['kind'] == 'method' else member}, 200

  async def rest_call(self, registry: str, key: str, name: str, body: Mapping) -> tuple[dict, int]:
    obj = self._rest_find(registry, key)
    if obj is None: return {'success': False, 'error': 'no such object'}, 404
    row = self._rest_rows(obj).get(name)
    if row is None or row['kind'] != 'method': return {'success': False, 'error': f'{name} is not a method'}, 405
    method, args = getattr(obj, name), dict(body)
    if row['async']: result = await method(**args)
    else: result = await asyncio.get_running_loop().run_in_executor(None, lambda: method(**args))
    return {'success': True, 'result': result}, 200
# endregion


# region async application
class AsyncApp(App, EventLoopBridge):
  """Application base for long-lived asyncio services.

  Override ``setup()`` for synchronous setup during construction with config ready,
  and async ``start()`` for work. Run with ``asyncio.run(MyApp().run())`` or
  ``await app.run()`` on a host's loop. In ``start()``, use ``self._spawn(coro)``
  for concurrent work; ``run()`` waits for start and its TaskGroup to finish.

  On that loop, ``await app.stop()`` cancels spawned tasks, not ``start()`` itself.
  Put resource cleanup in the owning coroutine's ``finally`` or async context;
  ``run()`` does not call ``stop()`` automatically.
  The app is an ``EventLoopBridge`` onto its own running loop, so off-loop threads
  ``schedule``/``submit``/``call`` work onto it.
  """

  _task_group: asyncio.TaskGroup | None
  _background_tasks: set[asyncio.Task[Any]]
  _loop: asyncio.AbstractEventLoop | None

  def __init__(self, name: str = '', **kw) -> None:
    super().__init__(name=name, **kw)
    self._task_group = None
    self._background_tasks = set()
    self._loop = None
    self.setup()

  def setup(self) -> None: pass
  async def start(self) -> None: pass

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    loop = self._loop
    if loop is None: raise RuntimeError(f'{self!r} is not running')
    return loop

  async def run(self) -> None:
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    try:
      self._loop = asyncio.get_running_loop()
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        await self.start()
    finally:
      self._task_group = None
      self._loop = None
      self._background_tasks.clear()

  async def stop(self) -> None:
    current = asyncio.current_task()
    tasks = [task for task in self._background_tasks if task is not current and not task.done()]
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)

  def _spawn[T](self, coroutine: Coroutine[Any, Any, T], /) -> asyncio.Task[T]:
    tasks = self._task_group
    if tasks is None:
      coroutine.close()
      raise RuntimeError(f'{self!r} is not running')
    try: task = tasks.create_task(coroutine)
    except BaseException:
      coroutine.close()
      raise
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
    return task
# endregion


# region API application
class APIApp(mixin_Rest, AsyncApp):
    """An AsyncApp that serves HTTP, the transport ``mixin_Rest`` leaves to its host: on uvicorn, at the ``host`` and ``port`` of its
    configuration, its own objects at ``/rest`` and each ASGI app ``apis()`` gives at its path.

    ``GET /rest`` lists the objects, ``GET /rest/{registry}/{key}`` reads one and ``GET /rest/{registry}/{key}/{name}`` one of its
    values, ``POST /rest/{registry}/{key}/{name}`` calls a method with the JSON body as its arguments. Override ``apis()``; override
    ``start()`` for work before serving and end it with ``await super().start()``. FastAPI and uvicorn come with the ``ld`` extra::

        class LDAPI(APIApp, _SQABase):   # its store: the configuration's `db`, the engine and each request's session
            def apis(self): return {'/ld/v1': ld.served({'/work': work.app}, self)}
    """

    def apis(self) -> dict[str, Any]:
        """path -> the FastAPI (or any ASGI) app served there."""
        return {}

    def asgi(self):
        """The app uvicorn serves: ``/rest``, and the apps of ``apis()`` at their paths."""
        from fastapi import Body, FastAPI, Response

        def answer(reply: tuple[Any, int]) -> Response:   # a value gppu holds (a time, a uri) is sent as its text
            return Response(json.dumps(reply[0], default=str, ensure_ascii=False), status_code=reply[1], media_type='application/json')

        root = FastAPI(title=self.name)

        @root.get('/rest')
        def objects(kind: str | None = None): return answer(self.rest_objects(kind, full=True))

        @root.get('/rest/{registry}/{key}')
        def read(registry: str, key: str): return answer(self.rest_read(registry, key))

        @root.get('/rest/{registry}/{key}/{name}')
        def value(registry: str, key: str, name: str): return answer(self.rest_read(registry, key, name))

        @root.post('/rest/{registry}/{key}/{name}')
        async def call(registry: str, key: str, name: str, body: dict = Body(default_factory=dict)):
            return answer(await self.rest_call(registry, key, name, body))

        for path, app in self.apis().items(): root.mount(path, app)
        return root

    async def start(self) -> None:
        import uvicorn
        await uvicorn.Server(uvicorn.Config(self.asgi(), host=self.my('host'), port=self.my('port'))).serve()
# endregion
