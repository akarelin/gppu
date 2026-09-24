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
"""
from __future__ import annotations

import asyncio
import inspect
from abc import abstractmethod
from pathlib import Path
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from typing import Any, final

from .gppu import Env, Logger, _Base, _DC, _mixin
from .environment import Environment

# region YMRO lifecycle
class _YMRO:
  """Base mixin class implementing Y2 Method Resolution Order (YMRO) lifecycle management.

  Provides stepped initialization, loading, starting, and stopping mechanisms across
  class hierarchies by discovering and invoking methods matching convention names
  for each lifecycle step.
  """
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


class _YInit(_YMRO):
  """Mixin class providing initialization lifecycle management for YMRO components.

  Requires subclasses to implement an abstract `__init` method and provides
  an idempotent `init()` method that invokes registered lifecycle callbacks
  and tracks initialization status via the `initialized` property.
  """
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
  """Mixin class providing loading lifecycle management for YMRO components.

  Requires subclasses to implement an abstract `__load` method and provides
  an idempotent `load()` method that asserts initialization, invokes registered
  lifecycle callbacks, and tracks loading status via the `loaded` property.
  """
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
  """Mixin class providing start and stop lifecycle management for YMRO components.

  Requires subclasses to implement an abstract `__start` method and provides
  idempotent `start()` and `stop()` methods that invoke registered lifecycle
  callbacks and track status via the `started` and `stopped` properties.
  """
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
      Environment.from_env(name=self.name, app_path=app_file.parent)   # the config, and what it constructs
    super().__init__(name=self.name, **kw)


class App(_App, _DC):
  """Synchronous utility: define an entry method and call it after construction.

  Read settings with ``self.my(...)``. Construction loads Environment and State
  beside the subclass when Env is uninitialized; an already loaded Env is reused.
  If loading configuration explicitly and needing State, use
  ``Environment.from_env(...)``; ``Env.from_env()`` and ``Env.from_dict()``
  only load Env.

  Usage::

      from gppu import App
      class Hello(App):
        def main(self):
          self.Info('Hello world')
      Hello().main()
  """
  pass
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

  AsyncApp includes this mixin; a host with its own lifecycle can compose it
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
class AsyncApp(mixin_Rest, App, EventLoopBridge):
  """Application base for long-lived asyncio services.

  Override ``setup()`` for synchronous setup during construction with config ready,
  and async ``start()`` for work. Run with ``asyncio.run(MyApp().run())`` or
  ``await app.run()`` on a host's loop. In ``start()``, use ``self._spawn(coro)``
  for concurrent work; ``run()`` waits for start and its TaskGroup to finish.

  On that loop, ``await app.stop()`` cancels spawned tasks, not ``start()`` itself.
  Put resource cleanup in the owning coroutine's ``finally`` or async context;
  ``run()`` does not call ``stop()`` automatically.
  The app is an ``EventLoopBridge`` onto its own running loop, so off-loop threads
  ``schedule``/``submit``/``call`` work onto it. See ``mixin_Rest`` for HTTP hosting.
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
