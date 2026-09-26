"""gppu.app — the kinds of application, and their two lifecycles.

    mixin_Stepper           the sync lifecycle: init → load → start → stop, each class's __init/__load/__start/__stop
    App                     name, configuration, logging
    ├── CliApp              runs ``main`` once; the command line gives its parameters, and prints what it returns
    └── AsyncApp            the async lifecycle: setup() at construction, async start(), run() with a TaskGroup
        ├── MqttApp         (gppu.iot) the same, holding the broker its configuration names
        └── TUIApp          (gppu.tui) the same, with a Textual screen on the same loop

A CliApp's ``main`` parameters come from the command line (gppu.params), and a parameter annotated with a Provider
receives a configured Connection (gppu.connections). From code, another app is started with ``run(MyApp, since='3d')``.

    from gppu import CliApp
    from gppu.data import Postgres

    class Archive(CliApp):
      def main(self, since: str = '7d', db: Postgres = 'pg-lake') -> dict:
        \"\"\"Archive what changed.\"\"\"
        return {'rows': db.scalar('select count(*) from files.lake')}

    if __name__ == '__main__': Archive.cli()
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, final

from .connections import close_all
from .gppu import Env, _Base, _DC
from .params import call, parser, resolve, schema


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
    Debug('BY', self.__class__.__qualname__)
    siblings = [c for c in reversed(self.__class__.__mro__) if c != _YMRO and issubclass(c, _YMRO)]
    step = 'init'
    for sibling in siblings:
      Debug('DG', f"  {sibling.__qualname__}")
      qname = f"{sibling.__qualname__}__{step}"
      if qname[0] != '_': qname = '_' + qname
      method = getattr(self, qname, None)
      if method:
        Debug('INFO', f"  {method.__qualname__}")
        initers = getattr(sibling, '_initers', [])
        for initer in initers: Debug('DIM', f"     {initer.__qualname__}")


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
class mixin_Stepper(YStepper, _Base): pass
# endregion


class App(_Base):
  """Name, configuration and logging; a subclass is one of the kinds below.

  The name is the file the subclass is written in, and names the configuration beside it: ``<name>.yaml`` or
  ``config.yaml``, searched upward. An Env already loaded is reused. The app's configuration is the table under its
  name when the configuration has one, the whole configuration otherwise; ``my`` reads it.
  """

  def __init__(self, name: str = '') -> None:
    source = Path(inspect.getfile(type(self))).resolve()
    name = name or source.stem
    if not Env.initialized: Env.from_env(name, source.parent)
    super().__init__()
    self._name = name
    if isinstance(Env.data.get(name), dict): self._config_from_key(name)

  @property
  def name(self) -> str: return self._name

  @property
  def host(self) -> str:
    """The host the app runs on, as its configuration and its topics name it."""
    return Env.host


class CliApp(App):
  """Runs ``main`` once; the command line gives its parameters. What it returns is printed as JSON on stdout; logs
  go to stderr."""

  def main(self, *a, **kw) -> Any: raise NotImplementedError(f'{type(self).__name__} defines no main')

  def params(self, **given: Any) -> dict[str, Any]:
    """main's keyword arguments: given, then configuration, then defaults, then Connections by type."""
    return resolve(self.main, given, self.config())

  def invoke(self, **given: Any) -> Any: return call(self.main, self.params(**given))

  @classmethod
  def cli(cls, argv: list[str] | None = None) -> Any:
    """Start from the command line; ``--schema`` prints the parameters instead. The process's Connections close
    when it returns: this is the outermost call, so nothing else still holds them."""
    app = cls()
    given = vars(parser(app.main, app.name).parse_args(argv))
    if given.pop('schema', False): return print(json.dumps(schema(app.main), indent=2))
    try: result = app.invoke(**given)
    finally: close_all()
    if result is not None: print(json.dumps(result, indent=2, default=str))
    return result


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

  def _get_loop(self) -> asyncio.AbstractEventLoop: raise NotImplementedError
# endregion


class AsyncApp(App, EventLoopBridge):
  """A long-lived asyncio service: ``setup()`` runs at construction with configuration ready, ``async start()`` does
  the work. ``run()`` runs start inside one TaskGroup and returns when start and everything it spawned with
  ``self._spawn(coro)`` have finished; ``stop()`` cancels the spawned work. Off-loop threads reach the app through
  ``schedule``, ``submit`` and ``call``. ``asyncio.run(MyApp().run())``, ``MyApp.cli()``, or on a host's loop
  ``await app.run()``.
  """

  # On Windows the selector loop, which aiomqtt needs; an app that starts asyncio subprocesses sets this False.
  SELECTOR_LOOP = True

  def __init__(self, name: str = '') -> None:
    super().__init__(name)
    self._task_group: asyncio.TaskGroup | None = None
    self._background_tasks: set[asyncio.Task[Any]] = set()
    self._event_loop: asyncio.AbstractEventLoop | None = None
    self.setup()

  def setup(self) -> None: pass
  async def start(self) -> None: pass

  async def run(self) -> None:
    """``start`` inside the app's TaskGroup; returns when start and everything it spawned have finished."""
    async with self._task_scope(): await self.start()

  @classmethod
  def cli(cls, argv: list[str] | None = None) -> None:
    try: run_loop(cls().run(), selector=cls.SELECTOR_LOOP)
    finally: close_all()

  @asynccontextmanager
  async def _task_scope(self):
    """The TaskGroup the app's work runs in, open for as long as the context is."""
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    self._event_loop = asyncio.get_running_loop()
    try:
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        yield
    finally:
      self._task_group, self._event_loop = None, None
      self._background_tasks.clear()

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    if self._event_loop is None: raise RuntimeError(f'{self!r} is not running')
    return self._event_loop

  async def stop(self) -> None:
    current = asyncio.current_task()
    tasks = [t for t in self._background_tasks if t is not current and not t.done()]
    for task in tasks: task.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)

  def _spawn[T](self, coroutine: Coroutine[Any, Any, T], /) -> asyncio.Task[T]:
    if self._task_group is None:
      coroutine.close()
      raise RuntimeError(f'{self!r} is not running')
    task = self._task_group.create_task(coroutine)
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
    return task


def run(app: type[App] | str, /, **given: Any) -> Any:
  """Start another app from code, as Windmill runs a script by path: its class, or ``module:Class``.

  A CliApp's parameters resolve as on its command line, without one. An AsyncApp is awaited when called from a
  running loop, run to completion otherwise. The Connections it used stay open: they are the caller's too, shared by
  uid.
  """
  if isinstance(app, str):
    import importlib
    module, _, attr = app.partition(':')
    app = getattr(importlib.import_module(module), attr)
  result = app().invoke(**given) if issubclass(app, CliApp) else app().run()
  if not inspect.iscoroutine(result): return result
  try: asyncio.get_running_loop()
  except RuntimeError: return run_loop(result, selector=app.SELECTOR_LOOP)
  return result


def run_loop[T](coroutine: Coroutine[Any, Any, T], /, *, selector: bool = True) -> T:
  """Run on a new event loop. On Windows ``selector`` picks the selector loop, because aiomqtt needs ``add_reader``,
  which the default Proactor loop lacks; the selector loop cannot start asyncio subprocesses there, so an app that
  does runs on the Proactor loop."""
  return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop if selector and sys.platform == 'win32' else None)


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
  REST_RESERVED = ('init', 'load', 'start', 'stop', 'initialize', 'terminate', 'setup', 'run')
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
      seen, stack = set(), [_Base, _DC]
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
