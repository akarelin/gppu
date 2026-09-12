"""gppu.app — application bases and lifecycle.

Home of the App class family and the YMRO (Y2 Method Resolution Order)
init→load→start lifecycle. Each step walks the MRO for ``__method``-named
methods on every ancestor and calls them in order, giving cooperative
multi-inheritance without explicit ``super()`` chains. Subclasses can extend
the lifecycle by overriding ``POSSIBLE_STEPS`` (e.g. Y2 adds ``refresh`` and
``publish``).

``AsyncApp`` is the conventional asyncio counterpart: construction runs a
synchronous ``setup()`` hook, and ``run()`` opens one ``TaskGroup`` before
calling ``start()``. Long-lived work is added with ``_spawn()``.
"""
from __future__ import annotations

import asyncio
import inspect
from abc import abstractmethod
from pathlib import Path
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any, final

from .gppu import Env, Logger, _Base, _DC, _mixin
import typing
from collections.abc import Mapping

# region YMRO lifecycle
class _YMRO:
  POSSIBLE_STEPS = ['init', 'load', 'start', 'stop']

  @property
  def _trace_mro(self) -> bool:
    return bool(getattr(self, 'args', {}).get('trace_mro', False))


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

  def _callall(self, method, *a, **kw):
    for callback in self._ymro(method): callback(*a, **kw)


class YInit(_YMRO):
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


class YLoad(YInit):
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


class YStart(YLoad):
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


YStepper = YStart
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


class App(_App, _DC): pass
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
  """The object surface: every object of the application answers for its own
  members, walked from the classes born under ``Env.app_path`` — a name a gppu
  base defines is never exposed. A transport binds the four ``rest_*`` calls,
  each answering ``(payload, status)``: a manifest, the objects, a read, a call.

  A member is a *value* (a ``_DC`` field, a property, or a method named in
  ``rest_read_methods``) or a *command* (a method marked ``rest_command``,
  granted in ``rest_commands`` by class name, or listed in the object's own
  ``commands``, which then dispatches through its ``command()``). Names in
  ``rest_redact`` and the lifecycle vocabulary are never members. The host sets
  the three ``rest_*`` settings from its config and names ``rest_registries``,
  as an app sets ``connection`` for ``mixin_Mqtt``.
  """
  rest_read_methods: tuple[str, ...] = ()
  rest_redact: tuple[str, ...] = ()
  rest_commands: dict[str, list[str]] = {}

  REST_RESERVED = (*_YMRO.POSSIBLE_STEPS, 'initialize', 'terminate', 'setup', 'run')
  _REST_FIELD   = '_DC.__init_subclass__.<locals>.getter'   # the getter _DC generates for a field
  _REST_SCALARS = {str: 'str', int: 'int', float: 'float', bool: 'bool', list: 'list', dict: 'dict'}
  _REST_CASTS   = {'str': str, 'int': int, 'float': float}
  _rest_manifest: dict | None = None

  # ~~ the host's part
  def rest_registries(self) -> dict[str, Mapping]:
    """name -> roster of live objects (key -> object); the host names its own."""
    return {'app': {getattr(self, 'name', 'app'): self}}

  # ~~ the classes
  def _rest_owned(self, cls: type, name: str) -> bool:
    """The application's own name: every class in the MRO that defines it is born under app_path."""
    home = str(Env.app_path)
    owners = [c for c in cls.__mro__ if name in c.__dict__]
    return bool(owners) and all(_born(c).startswith(home) for c in owners)

  @staticmethod
  def _rest_hints(obj) -> dict:
    """Resolved annotations; one the walk cannot resolve (a forward name nothing imports) reads as 'any'."""
    try: return typing.get_type_hints(obj)
    except Exception: return dict(getattr(obj, '__annotations__', {}) or {})

  def _rest_type(self, hint) -> str:
    named = [a for a in typing.get_args(hint) if a is not type(None)]
    if named and (typing.get_origin(hint) or hint) not in self._REST_SCALARS: hint = named[0]
    return self._REST_SCALARS.get(typing.get_origin(hint) or hint, 'any')

  def _rest_members(self, cls: type) -> dict[str, dict]:
    fields, rows = self._rest_hints(cls), {}
    for name in dir(cls):
      if name[0] == '_' or name in self.REST_RESERVED or name in self.rest_redact: continue
      if not self._rest_owned(cls, name): continue
      member = inspect.getattr_static(cls, name, None)
      if isinstance(member, property):
        if member.fget is None: continue
        generated = member.fget.__qualname__ == self._REST_FIELD
        hint = fields.get(name) if generated else self._rest_hints(member.fget).get('return')
        rows[name] = {'kind': 'field' if generated else 'value', 'type': self._rest_type(hint), 'call': False}
        continue
      fn = getattr(member, '__func__', member)
      if not inspect.isfunction(fn): continue
      sig, hints = inspect.signature(fn), self._rest_hints(fn)
      params = [p for n, p in sig.parameters.items() if n not in ('self', 'cls')]
      needed = [p for p in params if p.default is p.empty and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]
      at = f'{Path(fn.__code__.co_filename).name}:{fn.__code__.co_firstlineno}'
      if name in self.rest_read_methods and not needed and not any(p.kind is p.VAR_POSITIONAL for p in params):
        rows[name] = {'kind': 'value', 'type': self._rest_type(hints.get('return')), 'call': True, 'at': at}
        continue
      marked  = bool(getattr(fn, 'rest_command', False))
      granted = any(name in self.rest_commands.get(c.__name__, []) for c in cls.__mro__)
      if not marked and not granted: continue
      if granted and (needed or any(p.kind is p.VAR_POSITIONAL for p in params)): continue
      rows[name] = {'kind': 'command', 'granted': granted, 'at': at, 'doc': (fn.__doc__ or '').split('\n')[0],
                    'args': {p.name: {'type': self._rest_type(hints.get(p.name)), 'required': p.default is p.empty}
                             for p in params if p.kind is not p.VAR_KEYWORD},
                    'free': any(p.kind is p.VAR_KEYWORD for p in params)}
    return rows

  def _rest_classes(self) -> list[type]:
    home = str(Env.app_path)
    seen, stack = set(), [_mixin, _Base, _DC]
    while stack:
      cls = stack.pop()
      if cls in seen: continue
      seen.add(cls); stack.extend(cls.__subclasses__())
    return sorted((c for c in seen if _born(c).startswith(home)), key=lambda c: c.__name__)

  @property
  def rest_manifest(self) -> dict:
    """The classes and their members, walked once."""
    if self._rest_manifest is None:
      home = str(Env.app_path)
      rows = {c.__name__: {'bases': [b.__name__ for b in c.__mro__[1:] if _born(b).startswith(home)],
                           'members': self._rest_members(c)} for c in self._rest_classes()}
      self._rest_manifest = {'registries': list(self.rest_registries()),
                             'classes': {n: c for n, c in rows.items() if c['members']}}
    return self._rest_manifest

  # ~~ the objects
  def _rest_find(self, registry: str, key: str):
    roster = self.rest_registries().get(registry) or {}
    return next((o for k, o in roster.items() if str(k) == key), None)

  def _rest_rows(self, obj) -> dict[str, dict]:
    rows = dict(self.rest_manifest['classes'].get(type(obj).__name__, {}).get('members', {}))
    for name in getattr(obj, 'commands', ()):                      # the instance declares these
      rows.setdefault(name, {'kind': 'command', 'granted': False, 'at': 'config', 'args': {}, 'free': True, 'doc': ''})
    return rows

  def _rest_address(self, obj) -> str:
    """Where this object answers, so a member that holds one carries a link."""
    for registry, roster in self.rest_registries().items():
      for key, other in roster.items():
        if other is obj: return f'{registry}/{key}'
    return ''

  def _rest_plain(self, value):
    """JSON the caller can read: an object of the application becomes its address, never its repr."""
    if value is None or isinstance(value, (str, int, float, bool)): return value
    if _born(type(value)).startswith(str(Env.app_path)): return self._rest_address(value) or type(value).__name__
    if isinstance(value, Mapping): return {str(k): self._rest_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)): return [self._rest_plain(v) for v in value]
    return str(value)

  def _rest_value(self, obj, name: str, row: dict):
    member = getattr(obj, name)
    return self._rest_plain(member() if row['call'] else member)

  def rest_payload(self, obj) -> dict:
    rows = self._rest_rows(obj)
    return {'class': type(obj).__name__,
            'members': {n: self._rest_value(obj, n, r) for n, r in rows.items() if r['kind'] != 'command'},
            'commands': {n: r['args'] for n, r in rows.items() if r['kind'] == 'command'}}

  def rest_bind(self, row: dict, body: Mapping) -> dict:
    """The body against a command's signature: exact names, scalar casts, no surprises."""
    args = row['args']
    unknown = [k for k in body if k not in args]
    if unknown and not row['free']: raise ValueError(f'unknown parameter(s) {unknown}; {sorted(args) or "none"} accepted')
    missing = [n for n, a in args.items() if a['required'] and n not in body]
    if missing: raise ValueError(f'missing parameter(s) {missing}')
    bound = {}
    for key, value in body.items():
      kind = args.get(key, {}).get('type', 'any')
      if kind in ('any', 'list', 'dict', 'bool') or key not in args:
        if kind in ('list', 'dict', 'bool') and not isinstance(value, {'list': list, 'dict': dict, 'bool': bool}[kind]):
          raise ValueError(f'{key}: expected {kind}, got {value!r}')
        bound[key] = value
        continue
      if isinstance(value, bool): raise ValueError(f'{key}: expected {kind}, got {value!r}')
      try: bound[key] = self._REST_CASTS[kind](value)
      except (TypeError, ValueError): raise ValueError(f'{key}: expected {kind}, got {value!r}')
    return bound

  # ~~ the four calls
  def rest_objects(self, kind: str | None = None, full: bool = False) -> tuple[dict, int]:
    out = {}
    for registry, roster in self.rest_registries().items():
      for key, obj in roster.items():
        if kind and type(obj).__name__ != kind: continue
        out[f'{registry}/{key}'] = self.rest_payload(obj) if full else type(obj).__name__
    return {'objects': out}, 200

  def rest_read(self, registry: str, key: str, name: str | None = None) -> tuple[dict, int]:
    obj = self._rest_find(registry, key)
    if obj is None: return {'success': False, 'error': 'no such object'}, 404
    if name is None: return self.rest_payload(obj), 200
    row = self._rest_rows(obj).get(name)
    if row is None: return {'success': False, 'error': f'{type(obj).__name__} exposes no {name!r}'}, 404
    if row['kind'] == 'command': return {'success': False, 'error': f'{name} is a command; POST it'}, 405
    return {name: self._rest_value(obj, name, row)}, 200

  async def rest_call(self, registry: str, key: str, name: str, body: Mapping) -> tuple[dict, int]:
    obj = self._rest_find(registry, key)
    if obj is None: return {'success': False, 'error': 'no such object'}, 404
    row = self._rest_rows(obj).get(name)
    if row is None or row['kind'] != 'command': return {'success': False, 'error': f'{name} is not a command'}, 405
    try: args = self.rest_bind(row, dict(body))
    except ValueError as error: return {'success': False, 'error': str(error)}, 400
    # The object's own gate where it has one: a name it declares in `commands`
    # goes through command(); a marked or granted method is called bound.
    declared = name in getattr(obj, 'commands', ())
    call = (lambda: obj.command(cmd=name, **args)) if declared else (lambda: getattr(obj, name)(**args))
    if not declared and inspect.iscoroutinefunction(getattr(obj, name)): result = await call()
    else: result = await asyncio.get_running_loop().run_in_executor(None, call)
    return {'success': True, 'result': self._rest_plain(result)}, 200
# endregion


# region async application
class AsyncApp(mixin_Rest, App, EventLoopBridge):
  """Application base for long-lived asyncio services.

  ``setup()`` runs after App/_DC construction. ``run()`` opens the application's
  TaskGroup and calls ``start()``. ``stop()`` cancels tasks created by ``_spawn()``.
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
