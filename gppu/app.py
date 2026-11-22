"""gppu.app — the apps with steps. See docs/app.md.

Env, ``_Base`` and ``App``, the regular app with no steps, are in gppu.gppu. Here is ``AsyncApp``, which composes # pyright: ignore[C0301:line-too-long]
``App`` with ``YStart``, the YMRO (Y2 Method Resolution Order) init, load and start steps; ``APIApp`` serves HTTP # type: ignore
on it. For Textual, use ``gppu.tui.TUIApp``; for MQTT, ``gppu.iot.MqttApp``.
"""
from __future__ import annotations

import asyncio
import heapq
import inspect
import os
import random
import threading
import time
from abc import abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from itertools import count
from typing import Any, ClassVar, final

from .gppu import App, Debug, Env, _Base, _DC, _mixin, glob, glob_list, now_ts, y2path
from .gppu import _YMRO, YInit, YLoad, YStart





# region event-loop bridge
type AsyncSubmission[T] = Future[T] | asyncio.Task[T]


class mixin_EventLoopBridge(_mixin):
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
      if mixin_EventLoopBridge._on_loop(loop): return loop.create_task(coroutine)
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


# region async application
# region - Timers: an async app's, held by one thread
def _callback_wrapper(callback: Callable[..., Any]) -> Callable[..., Any]:
  """The callback called with only the keywords it takes."""
  signature = inspect.signature(callback)

  def wrapped(*args: Any, **data: Any) -> Any:
    if not signature.parameters: return callback()
    if any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values()):
      return callback(*args, **data)
    allowed = {
      name for name, param in signature.parameters.items()
      if param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
    }
    return callback(*args, **{k: v for k, v in data.items() if k in allowed})

  return wrapped


@dataclass
class TimerHandle:
  """An armed timer: the callback's name, whether it fires once or repeats, its interval, and when it next fires
  (epoch seconds)."""
  id: int
  name: str = ''
  kind: str = ''
  interval: float | None = None
  next_run: float = 0.0
  _cancelled: bool = False
  _spent: bool = False          # .. a one-shot that has fired

  def cancel(self) -> None:
    self._cancelled = True

  @property
  def running(self) -> bool:
    return not self._cancelled and not self._spent


class _Scheduler:
  """One thread holds every armed timer, instead of one thread per arm.

  `threading.Timer` parks an OS thread for the whole delay, and `run_every`
  builds a fresh one on every tick: the live process carried 976 parked
  threads having created 460,972 of them at ~8/s. A due callback still gets a
  thread of its own, so one slow callback cannot hold up the rest — the same
  concurrency the Timer-per-arm had, without the parked threads.

  Deadlines are monotonic (a wall-clock step must not move an armed timer);
  `TimerHandle.next_run` stays epoch seconds, which is what the container view
  renders. A cancelled entry is skipped when it comes due rather than removed,
  so the heap holds it until then."""

  def __init__(self) -> None:
    self._heap: list[tuple[float, int, TimerHandle, Callable[[], None]]] = []
    self._wake = threading.Condition()
    self._thread: threading.Thread | None = None

  def arm(self, handle: TimerHandle, fire: Callable[[], None], delay: float) -> None:
    with self._wake:
      heapq.heappush(self._heap, (time.monotonic() + delay, handle.id, handle, fire))
      if self._thread is None:
        self._thread = threading.Thread(target=self._run, name='y2-timers', daemon=True)
        self._thread.start()
      self._wake.notify()

  def _run(self) -> None:
    while True:
      with self._wake:
        while not self._heap: self._wake.wait()
        due, _, handle, fire = self._heap[0]
        remaining = due - time.monotonic()
        if remaining > 0:
          self._wake.wait(remaining)      # .. a nearer arm notifies; re-read the head
          continue
        heapq.heappop(self._heap)
      if handle._cancelled: continue
      threading.Thread(target=fire, daemon=True).start()


_SCHEDULER = _Scheduler()
# endregion



class AsyncApp(App, YStart, mixin_EventLoopBridge):
  """Application base for long-lived asyncio services, on the YMRO steps.

  Construction runs init; ``run()`` runs init (light loading, with the configuration ready),
  load (the heavy loading) and start, last, on the app's loop: ``asyncio.run(MyApp().run())``.
  A class gives its part of a step as a private ``__init``, ``__load``, ``__start`` or ``__stop``, sync or
  ``async def``, with no super: every class's part runs, base first.
  A part adds concurrent work with ``self._spawn(coro)``; ``run()`` returns when all of it
  has finished, and ``app.stop()`` cancels it.
  The app is a ``mixin_EventLoopBridge`` onto its own running loop, so off-loop threads
  ``schedule``/``submit``/``call`` work onto it.

  Its timers: ``run_later`` fires a callback once after a delay, and arming it again under the same key replaces it;
  ``run_every`` fires it at an interval. ``timers`` holds every armed timer by its id, ``h_timeouts`` those armed under
  a key.

  Its objects are the rows of the list at its ``key``, each ``cls(data=row, parent=self)`` of the class its ``kind``
  names in ``_supported_types``; its steps start and stop them. With a ``poll_interval`` it refreshes them one at a
  time, each once per ``poll_interval``, starting ``poll_delay`` after it starts, in an order shuffled every round.
  """
  key: str
  poll_interval: int
  poll_delay: int

  _task_group: asyncio.TaskGroup | None
  _background_tasks: set[asyncio.Task[Any]]
  _loop: asyncio.AbstractEventLoop | None
  _timer_ids = count(1)
  _supported_types: ClassVar[dict] = {}
  restartable: ClassVar[bool] = True   # .. whether Runtime.restart_app may stop, reconstruct and start it

  def __init(self) -> None:
    self._task_group = None
    self._background_tasks = set()
    self._loop = None
    self.timers: dict[int, TimerHandle] = {}
    self.h_timeouts: dict[str, TimerHandle] = {}
    self._my_groups: list = []
    self._polled: list = []
    for data in glob_list(self.key): self._add_group(data)

  def _add_group(self, data: dict) -> None:
    self._my_groups.append(self._supported_types[data['kind']](data=data, parent=self))

  def __start(self) -> None:
    for group in self._my_groups: group.start()
    if self.poll_interval: self.run_every(self._cb_poll, start=self.poll_delay, interval=self.poll_interval / len(self._my_groups))

  def _cb_poll(self) -> None:
    if not self._polled: self._polled = random.sample(self._my_groups, len(self._my_groups))
    self._polled.pop().refresh()

  def run_later(self, callback: Callable[..., Any], *, delay: int | float, key: str | None = None, **data: Any) -> TimerHandle:
    if key is not None:
      previous = self.h_timeouts.pop(key, None)
      if previous is not None:
        previous.cancel()
        self.timers.pop(previous.id, None)
    name = getattr(callback, '__name__', '') or getattr(getattr(callback, 'func', None), '__name__', '')
    callback = _callback_wrapper(callback)
    handle = TimerHandle(id=next(self._timer_ids), name=name, kind='once', next_run=now_ts() + float(delay))

    def wrapped() -> None:
      handle._spent = True                  # .. a one-shot is spent once it fires, and so is its slot under the key
      self.timers.pop(handle.id, None)
      if self.h_timeouts.get(key) is handle: del self.h_timeouts[key]
      if handle._cancelled: return
      callback(**data)

    self.timers[handle.id] = handle
    if key is not None: self.h_timeouts[key] = handle
    _SCHEDULER.arm(handle, wrapped, float(delay))
    return handle

  def run_every(self, callback: Callable[..., Any], *, start: int | float, interval: int | float, **data: Any) -> TimerHandle:
    name = getattr(callback, '__name__', '') or getattr(getattr(callback, 'func', None), '__name__', '')
    callback = _callback_wrapper(callback)
    handle = TimerHandle(id=next(self._timer_ids), name=name, kind='interval',
                         interval=float(interval), next_run=now_ts() + float(start))

    def wrapped() -> None:
      if handle._cancelled: return
      try:
        callback(**data)
      finally:
        # .. Space completions without overlap; a failed poll must not stop the timer.
        if not handle._cancelled:
          handle.next_run = now_ts() + float(interval)
          _SCHEDULER.arm(handle, wrapped, float(interval))

    self.timers[handle.id] = handle
    _SCHEDULER.arm(handle, wrapped, float(start))
    return handle

  def cancel_timer(self, handle: TimerHandle) -> None:
    handle.cancel()
    self.timers.pop(handle.id, None)

  def timer_running(self, handle: TimerHandle) -> bool:
    return handle.running

  def cancel_timers(self) -> None:
    """Every timer this app armed, cancelled."""
    for handle in list(self.h_timeouts.values()) + list(self.timers.values()):
      handle.cancel()
    self.timers.clear()
    self.h_timeouts.clear()

  def __stop(self) -> None:
    for group in self._my_groups: group.stop()
    loop = self._loop
    if loop is None: return                    # .. not running: nothing it spawned is left to cancel
    try: on_loop = asyncio.get_running_loop() is loop
    except RuntimeError: on_loop = False
    if not on_loop:                            # .. stopped from another thread: the loop cancels its own tasks
      loop.call_soon_threadsafe(lambda: [task.cancel() for task in list(self._background_tasks) if not task.done()])
      return
    current = asyncio.current_task()
    for task in self._background_tasks:
      if task is not current and not task.done(): task.cancel()

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    loop = self._loop
    if loop is None: raise RuntimeError(f'{self!r} is not running')
    return loop

  async def run(self) -> None:
    """init, load and start on this loop; returns when the work they spawned has finished."""
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    try:
      self._loop = asyncio.get_running_loop()
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        for step in (self.init, self.load, self.start):
          if result := step(): await result
    finally:
      self._task_group = None
      self._loop = None
      self._background_tasks.clear()

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

  async def launch(self, command: list[str], line: Callable[[str], Any], cwd: str, env: dict) -> str | None:
    """Start a process and hand `line` each line of its output; the error, or None when it exits with 0."""
    try:
      process = await asyncio.create_subprocess_exec(
        *command, cwd=cwd, env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
      )
      async for raw in process.stdout:
        line(raw.decode('utf-8', errors='replace').rstrip())
      if code := await process.wait():
        return f'process exited with {code}'
    except OSError as failure:
      return str(failure)
    return None

  async def run_parallel(self, units: list, run: Callable[[Any], Coroutine], conflicts: Callable[[Any, list], bool],
                         failed: Callable[[Any, BaseException], Any]) -> None:
    """Run every unit at once with `run`. A unit waits while `conflicts(unit, running)` says it clashes with one that
    is running, and starts when that one ends; `failed` hears of a unit whose run raised, as it ends."""
    pending, running = list(units), {}
    while pending or running:
      for unit in pending[:]:
        if conflicts(unit, list(running.values())): continue
        running[asyncio.create_task(run(unit))] = unit
        pending.remove(unit)
      finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
      for task in finished:
        unit = running.pop(task)
        if task.exception(): failed(unit, task.exception())
# endregion


# region - Runtime: Y2's, the program's apps and who listens to what
@dataclass(frozen=True)
class ListenerHandle:
  """A registered listener: its id, and the call that removes it."""
  id: int
  cancel: Callable[[], None]


class _Runtime:
  """The program's apps, which all share it: ``apps`` by name, the registries they fill (``actions``, ``buttons``,
  ``indicators``), and the listeners to events, to entity states and to topics. ``Runtime`` is its one instance. A
  callback is called with only the keywords it takes."""

  def __init__(self) -> None:
    self._init_runtime()

  def _init_runtime(self) -> None:
    self.apps: dict[str, Any] = {}
    self.actions: dict[str, Any] = {}
    self.buttons: dict[str, Any] = {}
    self.indicators: dict[str, Any] = {}
    self.event_listeners: dict[int, tuple[str | None, Callable[..., Any], dict[str, Any]]] = {}
    self.state_listeners: dict[int, tuple[Any, str | None, Callable[..., Any], dict[str, Any]]] = {}
    self.topic_listeners: dict[int, tuple[y2path | None, Callable[..., Any], dict[str, Any]]] = {}
    self._listener_ids = count(1)
    self.data = {
      'apps': self.apps,
      'actions': self.actions,
      'buttons': self.buttons,
      'indicators': self.indicators,
    }

  def reset(self) -> None:
    """Every app's timers cancelled, and the apps, the registries and the listeners empty."""
    for app in self.apps.values():
      app.cancel_timers()
    self._init_runtime()

  def register_app(self, app: Any) -> None:
    self.apps[app.name] = app

  def restart_app(self, name: str) -> Any:
    """Stop one app, discard it, and start a fresh instance of the same class from the same data. Raises for an unknown
    or non-restartable name."""
    app = self.apps.get(name)
    if app is None:
      raise ValueError(f"Unknown app: {name}")
    if not app.restartable:
      raise ValueError(f"App is not restartable: {name}")
    app.stop()
    self.apps.pop(name, None)
    new_app = type(app)(data=dict(app.data))
    new_app.start()
    return new_app

  def listen_event(self, callback: Callable[..., Any], *, event: str | None = None, **data: Any) -> ListenerHandle:
    callback = _callback_wrapper(callback)
    key = next(self._listener_ids)
    self.event_listeners[key] = (event, callback, dict(data))

    def cancel() -> None:
      self.event_listeners.pop(key, None)

    return ListenerHandle(id=key, cancel=cancel)

  def fire_event(self, event: str, **data: Any) -> None:
    for expected, callback, listener_data in tuple(self.event_listeners.values()):
      if expected is not None and expected != event: continue
      callback(event=event, data=dict(data), **listener_data)

  def listen_state(self, callback: Callable[..., Any], *, eid: Any = None, attribute: str | None = None,
                   **data: Any) -> ListenerHandle:
    from .iot import y2eid   # .. an entity's id is IoT's type, and gppu.iot is built on this module
    parsed = y2eid(eid) if eid else None
    callback = _callback_wrapper(callback)
    key = next(self._listener_ids)
    self.state_listeners[key] = (parsed, attribute, callback, dict(data))

    def cancel() -> None:
      self.state_listeners.pop(key, None)

    return ListenerHandle(id=key, cancel=cancel)

  def state_changed(self, entity: Any, *, old_state: Any, old_attrs: Mapping[str, Any]) -> None:
    changes: list[tuple[str | None, Any, Any]] = []
    if old_state != entity.state:
      changes.append((None, old_state, entity.state))
    for attr in sorted(set(old_attrs) | set(entity.attributes)):
      old = old_attrs.get(attr)
      new = entity.attributes.get(attr)
      if old != new:
        changes.append((attr, old, new))
    for attribute, old, new in changes:
      for expected_eid, expected_attr, callback, data in tuple(self.state_listeners.values()):
        if expected_eid is not None and expected_eid != entity.eid: continue
        if expected_attr != '*' and expected_attr != attribute: continue
        callback(entity=entity, attribute=attribute, old=old, new=new, **data)

  def listen_topic_state(self, callback: Callable[..., Any], *, path: str | y2path | None = None, **data: Any) -> ListenerHandle:
    parsed = y2path(path) if path else None
    callback = _callback_wrapper(callback)
    key = next(self._listener_ids)
    self.topic_listeners[key] = (parsed, callback, dict(data))

    def cancel() -> None:
      self.topic_listeners.pop(key, None)

    return ListenerHandle(id=key, cancel=cancel)

  def topic_changed(self, path: y2path, *, old: Any, new: Any) -> None:
    if old == new: return
    for expected_path, callback, data in tuple(self.topic_listeners.values()):
      if expected_path is not None and expected_path != path: continue
      callback(path=path, old=old, new=new, **data)


Runtime = _Runtime()
# endregion




# region - REST surface
class mixin_Rest:
  """Every public member of the application's own classes, over HTTP, and nothing
  declared. A field or property reads; a method is called with the JSON body as
  its keyword arguments; a synchronous method needing none answers a GET as well.
  A name is the application's when a class born in the application's folder, the
  folder of the file that defines the app, defines it — a base may define it too —
  and the private names and the lifecycle steps are the only exclusion.

  The universal REST API to any object. It works only in an AsyncApp. It is not the default: no gppu app
  includes it; an application that wants it composes it before its application
  base, as Y2 does. Override ``rest_registries()`` with
  ``{registry: {key: object}}``; by default it contains the app itself. The HTTP
  host serves ``rest_manifest`` and binds ``rest_objects``, ``rest_read`` and
  awaited ``rest_call``, which return ``(payload, status)``. The host supplies
  the HTTP listener and JSON serialization.
  """
  REST_RESERVED = (*_YMRO.POSSIBLE_STEPS, 'initialize', 'terminate', 'setup', 'run')

  @staticmethod
  def _born(cls: type) -> str: # type: ignore
    """Where a class's source lives; a built-in has none."""
    try: return inspect.getsourcefile(cls) or ''
    except TypeError: return ''
  _rest_manifest: dict | None = None

  def _rest_home(self) -> str:
    """The application's folder: where the file that defines the app lives, and its own classes with it."""
    return os.path.dirname(self._born(type(self)))

  def rest_registries(self) -> dict[str, Mapping]:
    """name -> roster of live objects (key -> object); the host names its own."""
    return {'app': {getattr(self, 'name', 'app'): self}}

  def _rest_members(self, cls: type) -> dict[str, dict]:
    home, rows = self._rest_home(), {}
    for name in dir(cls):
      if name[0] == '_' or name in self.REST_RESERVED: continue
      if not any(self._born(c).startswith(home) for c in cls.__mro__ if name in c.__dict__): continue
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
    """The classes born in the application's folder and their members, walked once."""
    if self._rest_manifest is None:
      seen, stack = set(), [_mixin, _Base, _DC]
      while stack:
        cls = stack.pop()
        if cls not in seen: seen.add(cls); stack.extend(cls.__subclasses__())
      home = self._rest_home()
      classes = {c.__name__: {'members': self._rest_members(c)} for c in sorted(seen, key=lambda c: c.__name__) if self._born(c).startswith(home)}
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


# region API application
class APIApp(AsyncApp):
    """An AsyncApp that serves HTTP: on uvicorn, at the ``host`` and ``port`` of its configuration, each ASGI app
    ``apis()`` gives at its path, from the end of ``start``. Override ``apis()``; work needed before serving is done
    in ``load``. FastAPI and uvicorn come with the ``ld`` extra::

        class LDAPI(APIApp, _SQABase):   # its store: the configuration's `db`, the engine and each request's session
            def apis(self): return {'/ld/v1': ld.serve({'/work': work.app}, self)}
    """

    def apis(self) -> dict[str, Any]:
        """path -> the FastAPI (or any ASGI) app served there."""
        return {}

    def asgi(self):
        """The app uvicorn serves: the apps of ``apis()`` at their paths."""
        from fastapi import FastAPI

        root = FastAPI(title=self.name)
        for path, app in self.apis().items(): root.mount(path, app)
        return root

    def __start(self) -> None:
        import uvicorn
        self._spawn(uvicorn.Server(uvicorn.Config(self.asgi(), host=self.my('host'), port=self.my('port'))).serve())
# endregion
