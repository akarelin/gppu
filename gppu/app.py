"""gppu.app — the kinds of application.

    App                     name, configuration, logging, and the parameters of ``main``
    ├── CliApp              runs ``main`` once and prints what it returns
    └── AsyncApp            runs ``main`` on an event loop with a TaskGroup for long-lived work
        └── TUIApp          (gppu.tui) the same, with a Textual screen on the same loop

Every kind is started the same way, ``MyApp.cli()``: the command line becomes ``main``'s parameters (gppu.params),
and a parameter annotated with a Provider receives a configured Connection (gppu.connections). From code, another
app is started with ``run(MyApp, since='3d')``, with the same resolution and no command line.

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
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from .connections import close_all
from .gppu import Env, _Base, _DC
from .params import call, parser, resolve, schema


class App(_Base):
  """Name, configuration and logging; a subclass defines ``main`` and is one of the kinds below.

  The name is the file the subclass is written in, and names the configuration beside it: ``<name>.yaml`` or
  ``config.yaml``, searched upward. An Env already loaded is reused. The app's configuration is the table under its
  name when the configuration has one, the whole configuration otherwise; ``my`` and ``main``'s parameters read it.
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

  def params(self, **given: Any) -> dict[str, Any]:
    """main's keyword arguments: given, then configuration, then defaults, then Connections by type."""
    return resolve(self.main, given, self.config())

  def main(self, *a, **kw) -> Any: raise NotImplementedError(f'{type(self).__name__} defines no main')

  def call_main(self, params: dict[str, Any]) -> Any:
    """main with resolved parameters; the positional-only ones go by position."""
    return call(self.main, params)

  def invoke(self, **given: Any) -> Any: raise NotImplementedError

  @classmethod
  def cli(cls, argv: list[str] | None = None) -> Any:
    """Start from the command line; ``--schema`` prints the parameters instead. The process's Connections close
    when it returns: this is the outermost call, so nothing else still holds them."""
    app = cls()
    given = vars(parser(app.main, app.name).parse_args(argv))
    if given.pop('schema', False): return print(json.dumps(schema(app.main), indent=2))
    try: return app._cli(given)
    finally: close_all()

  def _cli(self, given: dict) -> Any: return self.invoke(**given)


class CliApp(App):
  """Runs ``main`` once. What it returns is printed as JSON on stdout; logs go to stderr."""

  def invoke(self, **given: Any) -> Any: return self.call_main(self.params(**given))

  def _cli(self, given: dict) -> Any:
    result = self.invoke(**given)
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
  """Runs ``async def main`` inside one TaskGroup; ``self._spawn(coro)`` adds long-lived work to it.

  ``invoke`` returns when main and everything it spawned have finished; ``stop()`` cancels the spawned work. Off-loop
  threads reach the app through ``schedule``, ``submit`` and ``call``. On a host's loop, ``await app.invoke(...)``.
  """

  # On Windows the selector loop, which aiomqtt needs; an app that starts asyncio subprocesses sets this False.
  SELECTOR_LOOP = True

  def __init__(self, name: str = '') -> None:
    super().__init__(name)
    self._task_group: asyncio.TaskGroup | None = None
    self._background_tasks: set[asyncio.Task[Any]] = set()
    self._event_loop: asyncio.AbstractEventLoop | None = None

  async def main(self, *a, **kw) -> Any: raise NotImplementedError(f'{type(self).__name__} defines no main')

  async def invoke(self, **given: Any) -> Any:
    params = self.params(**given)
    async with self._task_scope():
      return await self.call_main(params)

  def _cli(self, given: dict) -> Any: return run_loop(self.invoke(**given), selector=self.SELECTOR_LOOP)

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

  Parameters resolve as on its command line, without one. An AsyncApp is awaited when called from a running loop,
  run to completion otherwise. The Connections it used stay open: they are the caller's too, shared by uid.
  """
  if isinstance(app, str):
    import importlib
    module, _, attr = app.partition(':')
    app = getattr(importlib.import_module(module), attr)
  result = app().invoke(**given)
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
