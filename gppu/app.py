"""gppu.app — application base, lifecycle, and async io.

Home of the App class family and the YMRO (Y2 Method Resolution Order)
init→load→start lifecycle. Each step walks the MRO for ``__method``-named
methods on every ancestor and calls them in order, giving cooperative
multi-inheritance without explicit ``super()`` chains. Subclasses can extend
the lifecycle by overriding ``POSSIBLE_STEPS`` (e.g. Y2 adds ``refresh`` and
``publish``).

``AsyncApp`` adds the io half: ``initialize()`` runs init/load/start and then
drives an asyncio loop that gathers every long-lived task registered via
``serve_task()``. Mixins (e.g. ``gppu.iot.mixin_Mqtt``) register their own
loops; an embedded host (uvicorn, Textual) can instead run init/load/start
itself and ``await self.serve()`` inside its own loop.
"""
from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import threading
from abc import abstractmethod
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Literal, Optional, TypeAlias, final

from .gppu import (Env, Logger, _Base, _DC, _mixin, dict_sanitize, dict_to_yml, now_ts)

_trace_mro = False


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
  """Base class for all apps. Inherits logging (_Logger) and config (_Config) with self.my().

  Auto-initializes Env from name + caller's directory if Env is not already initialized.
  """
  name: str = ''

  def __init__(self, name: str = '', **kw) -> None:
    caller_file = Path(inspect.stack()[1].filename).resolve()
    self.name = name or caller_file.stem
    if not Env.initialized:
      Env.from_env(name=self.name, app_path=caller_file.parent)
    super().__init__(name=self.name, **kw)


class App(_App, _DC): pass
# endregion


# region async YMRO lifecycle
class aYMRO:
  """Async parallel of _YMRO. ``init``/``load``/``start`` are coroutines that
  await each ancestor's ``__init``/``__load``/``__start`` step in MRO order; a
  step may be sync or ``async def``. The async mixin also owns the loop: ``_spawn``
  registers a background coroutine that ``start``'s TaskGroup keeps alive. The sync
  _YMRO / mixin_Stepper are left untouched for AppDaemon/Y2."""
  POSSIBLE_STEPS = ['init', 'load', 'start', 'stop']

  def _aymros(self) -> dict:
    result = {}
    siblings = [c for c in reversed(type(self).__mro__) if c is not aYMRO and c is not object]
    for step in self.POSSIBLE_STEPS:
      result[step] = []
      for sibling in siblings:
        qname = f"{sibling.__qualname__}__{step}"
        if qname[0] != '_': qname = '_' + qname
        method = getattr(self, qname, None)
        if method: result[step].append(method)
    return result

  def _aymro(self, method: str) -> list: return self._aymros().get(method, [])

  async def _acallall(self, method: str, *a, **kw) -> None:
    for m in self._aymro(method):
      result = m(*a, **kw)
      if asyncio.iscoroutine(result): await result

  # the loop's callback mechanism mixin_Timers / mixin_Mqtt / mixin_Http build on;
  # internal — capability mixins call it, app code does not.
  _tg: asyncio.TaskGroup

  def _spawn(self, coro) -> asyncio.Task:
    """Schedule a background coroutine in the app's TaskGroup (opened by
    ``start``); returns its Task. A long-lived one (the mqtt loop, a
    ``run_every``) is what keeps the app alive. Per the asyncio docs,
    ``create_task`` is allowed from within a running task while the group is
    active, so a callback may spawn further work (e.g. ``run_later``)."""
    return self._tg.create_task(coro)


class aYInit(aYMRO):
  async def __init(self): pass        # no-op default; a step is optional, override as needed

  async def init(self):
    if self.initialized: return
    await self._acallall('init')
    self.initialized = True

  @property
  def initialized(self) -> bool: return getattr(self, '_initialized', False)
  @initialized.setter
  def initialized(self, value: bool): self._initialized = value


class aYLoad(aYInit):
  async def __load(self): pass

  async def load(self):
    if self.loaded: return
    assert self.initialized
    await self._acallall('load')
    self.loaded = True

  @property
  def loaded(self) -> bool: return getattr(self, '_loaded', False)
  @loaded.setter
  def loaded(self, value: bool): self._loaded = value


class aYStart(aYLoad):
  async def __start(self): pass

  async def initialize(self):
    """Entry point: run the async lifecycle. ``start`` opens the main loop, so
    this runs until the app is stopped — ``asyncio.run(app.initialize())``."""
    await self.init(); await self.load(); await self.start()

  async def start(self):
    """Start the main loop. Opens the TaskGroup, runs the __start steps (where
    mixins spawn their loops/timers), then keeps the app alive on those tasks —
    propagating the first non-cancel failure as an ExceptionGroup."""
    if self.started: return
    async with asyncio.TaskGroup() as tg:
      self._tg = tg
      await self._acallall('start')
      self.started = True

  async def stop(self):
    if self.stopped: return
    await self._acallall('stop')
    self.started = False
    self.stopped = True
    self.loaded = False

  @property
  def started(self) -> bool: return getattr(self, '_started', False)
  @started.setter
  def started(self, value: bool): self._started = value
  @property
  def stopped(self) -> bool: return getattr(self, '_stopped', False)
  @stopped.setter
  def stopped(self, value: bool): self._stopped = value


aYStepper = aYStart
class mixin_aStepper(aYStepper, _mixin): pass
# endregion


# region mixin_Timers
class protocol_Async(mixin_aStepper):
  """Type-only surface the capability mixins (Timers/Mqtt/Http) rely on the
  composed AsyncApp to provide via aYMRO."""
  _spawn: Callable[..., asyncio.Task]


class mixin_Timers(protocol_Async, _mixin):
  """run_every / run_later on top of the async loop (``spawn``). A timer handle
  is the underlying ``asyncio.Task``; callbacks may be sync or async and receive
  ``**data`` as keyword arguments."""

  def __init(self):
    self._h_timeouts: dict = {}          # key -> Task (for keyed run_later debounce)

  async def run_every(self, cb: Callable, start='now', interval: float = 60, **data) -> asyncio.Task:
    """Run ``cb`` every ``interval`` seconds. ``start='now'`` fires the first run
    immediately; a number delays the first run that many seconds."""
    delay = 0.0 if start == 'now' else float(start)
    return self._spawn(self._run_every(cb, delay, float(interval), data))

  async def run_later(self, cb: Callable, delay: float = 180, key: str | None = None, **data) -> asyncio.Task:
    """Run ``cb`` once after ``delay`` seconds. With ``key``, rearming cancels
    the pending timer under that key and replaces it (debounce)."""
    if key:
      old = self._h_timeouts.pop(key, None)
      if old is not None and not old.done(): old.cancel()
    task = self._spawn(self._run_later(cb, float(delay), data))
    if key: self._h_timeouts[key] = task
    return task

  async def _run_every(self, cb, delay, interval, data):
    if delay: await asyncio.sleep(delay)
    while True:
      await self._fire(cb, data)
      await asyncio.sleep(interval)

  async def _run_later(self, cb, delay, data):
    await asyncio.sleep(delay)
    await self._fire(cb, data)

  async def _fire(self, cb, data):
    try:
      result = cb(**data)
      if asyncio.iscoroutine(result): await result
    except asyncio.CancelledError:
      raise
    except Exception as e:
      Logger.Warn('timer callback error:', getattr(cb, '__name__', repr(cb)), e)
# endregion


# region AsyncApp
class AsyncApp(App, mixin_aStepper):
  """App + the async lifecycle/loop (mixin_aStepper). Run it with
  ``asyncio.run(app.initialize())`` — init → load → start, where ``start`` opens
  the main loop. Compose capability mixins on top — ``mixin_Timers`` /
  ``mixin_Mqtt`` / ``mixin_Http`` — each spawning its work in its async
  ``__start`` step."""
# endregion


# region Tracing decorators
_TracerAction: TypeAlias = Literal['before', 'after', 'instead']

TA_BEFORE: _TracerAction = 'before'
TA_AFTER: _TracerAction = 'after'
TA_INSTEAD: _TracerAction = 'instead'
TAs: list[_TracerAction] = [TA_BEFORE, TA_AFTER, TA_INSTEAD]


def _tracer(tracer: Optional[Callable[..., Any]] = None, action: Optional[_TracerAction] = None) -> Callable:
  def decorator(method: Callable) -> Callable:
    def wrapper(self, *a, **kw):
      if not tracer: return method(self, *a, **kw)
      if action == TA_BEFORE:
        tracer(self, *a, **kw)
        return method(self, *a, **kw)
      if action == TA_AFTER:
        _ = method(self, *a, **kw)
        tracer(self, *a, **kw)
        return _
      if action == TA_INSTEAD:
        return tracer(self, *a, **kw)
    return wrapper
  return decorator

# endregion


# region Tracer
"""Y2 flight-recorder tracer (relocated from Y2's y2trace into gppu.app).

Records, as newline-delimited JSON under ``trace_folder``, everything needed
to reconstruct what happened as a result of an external event:

  * ``object``  — each object's data dict at the end of ``init`` and ``start``
                  (creation params + post-step state).
  * ``trigger`` — every external event AppDaemon fires for Y2 to consume
                  (MQTT message arrival, external entity state change), captured once.
  * ``event``   — every callback AppDaemon actually dispatched, tagged with the
                  ``seq`` of the trigger that caused it (trigger -> reaction linkage).
  * ``state``   — periodic marker; the full global ``State`` is dumped to a yml.

All hooks are installed at runtime from ``Tracer.install`` (called once during
``Environment.initialize``) by monkeypatching the lifecycle and AppDaemon's
event/dispatch machinery — no AppDaemon source is modified.  Disabled by
default; every write is guarded so tracing can never break the app.
"""


class Tracer:
  enabled: bool = False
  folder: str = '.'
  path: str | None = None                 # {folder}/{filename}
  state_filename: str = 'state.yml'

  _installed: bool = False
  _fh: Any = None
  _lock = threading.Lock()
  _trigger_seq = itertools.count(1)
  _cur_trigger: ContextVar = ContextVar('y2_trace_trigger', default=None)

  # ~~                              config + sink

  @classmethod
  def configure(cls, folder: str, enabled: bool = True, filename: str = 'y2-trace.jsonl') -> None:
    cls.folder = folder or '.'
    cls.enabled = bool(enabled)
    cls.path = f"{cls.folder}/{filename}"
    if not cls.enabled:
      return
    try:
      with cls._lock:
        if cls._fh is None:
          cls._fh = open(cls.path, 'a', encoding='utf-8')
    except Exception:
      cls.enabled = False

  @classmethod
  def _write(cls, record: dict) -> None:
    if not (cls.enabled and cls._fh):
      return
    try:
      line = json.dumps(dict_sanitize(record), ensure_ascii=False, default=str)
    except Exception:
      return
    try:
      with cls._lock:
        cls._fh.write(line + '\n')
        cls._fh.flush()
    except Exception:
      pass

  @classmethod
  def record(cls, kind: str, **fields) -> None:
    if cls.enabled:
      cls._write({'ts': now_ts(), 'kind': kind, **fields})

  # ~~                              capture

  @classmethod
  def snapshot_object(cls, obj, stage: str) -> None:           # features 1 + 2
    if not cls.enabled:
      return
    data = getattr(obj, 'data', None)
    if not (isinstance(data, dict) and data):
      data = getattr(obj, '_my', None)
    cls.record('object', klass=type(obj).__qualname__,
               name=getattr(obj, 'name', None), stage=stage, data=data)

  @classmethod
  def trigger(cls, namespace: str, data: dict) -> None:        # feature 4 — external event (primary)
    if not cls.enabled:
      return
    et = data.get('event_type', '') or ''
    if et.startswith('__') or namespace == 'admin':            # skip AD-internal/admin noise
      return
    seq = next(cls._trigger_seq)
    cls._cur_trigger.set(seq)
    d = data.get('data', {}) or {}
    rec = {'seq': seq, 'ns': namespace, 'event_type': et}
    if et == 'state_changed':
      rec |= {'entity': d.get('entity_id'),
              'old': (d.get('old_state') or {}).get('state'),
              'new': (d.get('new_state') or {}).get('state')}
    else:
      rec |= {'data': d}                                       # mqtt: topic/payload
    cls.record('trigger', **rec)

  @classmethod
  def event(cls, name: str, args: dict) -> None:               # feature 4 — callback fired (reaction)
    if not cls.enabled:
      return
    fn = args.get('function')
    fn = getattr(fn, 'func', fn)
    rec = {'seq': cls._cur_trigger.get(), 'app': name, 'cbtype': args.get('type'),
           'cb': getattr(fn, '__qualname__', str(fn)), 'kwargs': args.get('kwargs')}
    if args.get('type') == 'state':
      rec |= {'entity': args.get('entity'), 'attribute': args.get('attribute'),
              'old': args.get('old_state'), 'new': args.get('new_state')}
    elif args.get('type') == 'event':
      rec |= {'event': args.get('event'), 'data': args.get('data')}
    cls.record('event', **rec)

  @classmethod
  def snapshot_state(cls, state) -> None:                      # feature 3 — periodic
    if not cls.enabled:
      return
    try:
      dict_to_yml(filename=f"{cls.folder}/{cls.state_filename}",
                  data={'data': state.data, 'cache': state.cache})
    except Exception:
      pass
    try:
      cls.record('state', stats=state.stats())
    except Exception:
      pass

  # ~~                              install hooks

  @classmethod
  def install(cls, ad) -> None:
    """Idempotently install runtime hooks.  ``ad`` is the AppDaemon instance (self.AD)."""
    if cls._installed:
      return
    cls._installed = True

    # (a) external event arrival — the trigger (PRIMARY)
    try:
      eklass = type(ad.events)
      _orig_pe = eklass.process_event

      async def _traced_pe(self, namespace, data, _orig=_orig_pe):
        try: Tracer.trigger(namespace, data)
        except Exception: pass
        return await _orig(self, namespace, data)

      eklass.process_event = _traced_pe
    except Exception:
      pass

    # (b) callbacks fired — the reaction
    try:
      tklass = type(ad.threading)
      _orig_dw = tklass.dispatch_worker

      async def _traced_dw(self, name, args, _orig=_orig_dw):
        try: Tracer.event(name, args)
        except Exception: pass
        return await _orig(self, name, args)

      tklass.dispatch_worker = _traced_dw
    except Exception:
      pass

    # (c) gppu lifecycle object snapshots (init / start)
    try:
      _orig_init = YInit.init
      _orig_start = YStart.start

      def _traced_init(self, _orig=_orig_init):
        was = getattr(self, 'initialized', False)
        _orig(self)
        if not was and getattr(self, 'initialized', False):
          try: Tracer.snapshot_object(self, 'init')
          except Exception: pass

      def _traced_start(self, _orig=_orig_start):
        was = getattr(self, 'started', False)
        _orig(self)
        if not was and getattr(self, 'started', False):
          try: Tracer.snapshot_object(self, 'start')
          except Exception: pass

      setattr(YInit, 'init', _traced_init)
      setattr(YStart, 'start', _traced_start)
    except Exception:
      pass
# endregion
