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
from collections.abc import Coroutine
from typing import Any, final

from .gppu import Env, Logger, _Base, _DC, _mixin

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


# region async application
class AsyncApp(App):
  """Application base for long-lived asyncio services.

  ``setup()`` runs after App/_DC construction. ``run()`` opens the application's
  TaskGroup and calls ``start()``. ``stop()`` cancels tasks created by ``_spawn()``.
  """

  _task_group: asyncio.TaskGroup | None
  _background_tasks: set[asyncio.Task[Any]]

  def __init__(self, name: str = '', **kw) -> None:
    super().__init__(name=name, **kw)
    self._task_group = None
    self._background_tasks = set()
    self.setup()

  def setup(self) -> None: pass
  async def start(self) -> None: pass

  async def run(self) -> None:
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    try:
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        await self.start()
    finally:
      self._task_group = None
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
