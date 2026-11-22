# .. archived 2026-11-22: what gppu's reduction removed from gppu/app.py, as it was last


# .. from fec31bb
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


# .. from fec31bb
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


# .. from fec31bb
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


# .. from fec31bb
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


# .. from gppu/v3.7.9
class _YMRO:
  POSSIBLE_STEPS = ['init', 'load', 'start', 'stop']

  @property
  def _trace_mro(self) -> bool:
    result = getattr(self, 'args', {}).get('trace_mro', False)
    global _trace_mro
    _trace_mro = result
    return result


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
    if any(inspect.iscoroutinefunction(m) for m in self._ymro(method)): return self._acallall(method, *a, **kw)
    [m(*a, **kw) for m in self._ymro(method)]

  async def _acallall(self, method: str, *a, **kw) -> None:
    for m in self._ymro(method):
      result = m(*a, **kw)
      if asyncio.iscoroutine(result): await result


# .. from gppu/v3.7.9
class mixin_Stepper(YStepper, _mixin): pass


class AsyncApp:
  # .. from fec31bb
  def cancel_timer(self, handle: TimerHandle) -> None:
    handle.cancel()
    self.timers.pop(handle.id, None)

  # .. from fec31bb
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

  # .. from fec31bb
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

  # .. from gppu/v3.7.9
  def __init__(self, **kw) -> None:
    super().__init__(**kw)
    self._task_group = None
    self._background_tasks = set()
    self._loop = None
    self.timers: dict[int, TimerHandle] = {}
    self.h_timeouts: dict[str, TimerHandle] = {}
    self.init()


class APIApp:
  # .. from fec31bb
    def __start(self) -> None:
        import uvicorn
        self._spawn(uvicorn.Server(uvicorn.Config(self.asgi(), host=self.my('host'), port=self.my('port'))).serve())
