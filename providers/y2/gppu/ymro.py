"""gppu.ymro — the Y2 init→load→start→stop lifecycle, from gppu 3 app.py unchanged.

YMRO (Y2 Method Resolution Order) walks the MRO for ``__method``-named methods on every ancestor and calls them in
order, giving cooperative multi-inheritance without explicit ``super()`` chains. Only Y2 uses it; where it lives is
Alex's decision (see README).
"""
from __future__ import annotations

from abc import abstractmethod
from typing import final

from gppu import _Base
from gppu.gppu import Debug


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
