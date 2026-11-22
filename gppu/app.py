"""gppu.app — the apps with steps. See docs/app.md.

Env, ``_Base`` and ``App``, the regular app with no steps, are in gppu.gppu. Here is ``AsyncApp``, which composes
``App`` with ``YStart``, the YMRO (Y2 Method Resolution Order) init, load and start steps. For Textual, use
``gppu.tui.TUIApp``; an async app with MQTT mixes in ``mixin_Mqtt``; ``gppu.api.APIApp`` serves HTTP.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import random
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future
from itertools import count
from typing import Any, ClassVar

import aiomqtt
import yaml
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .gppu import App, Env, YmlLoader, _Base, _DC, _mixin, deepset, glob_list, jinja, now_ts, sync, y2topic
from .gppu import _YMRO, YStart





# region async application
# region - a callback, called with only the keywords it takes
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


# endregion



class AsyncApp(App, YStart):
  """Application base for long-lived asyncio services, on the YMRO steps.

  Construction runs init; ``run()`` runs init (light loading, with the configuration ready),
  load (the heavy loading) and start, last, on the app's loop: ``asyncio.run(MyApp().run())``.
  A class gives its part of a step as a private ``__init``, ``__load``, ``__start`` or ``__stop``, an ``async def``
  one with ``@sync``, with no super: every class's part runs, base first.
  A part adds concurrent work with ``self._spawn(coro)``. A started app runs until it is stopped: ``app.stop()`` cancels
  its work and its timers, and ``run()`` returns. Another thread runs a coroutine on the app's loop with ``schedule``.

  Its timers: ``run_later`` fires a callback once after a delay, and arming it again under the same key replaces it;
  ``run_every`` fires it at an interval. ``timers`` holds every armed timer's row by its id (its callback's name, its
  kind, its interval and its next run in epoch seconds), ``h_timeouts`` those armed under a key.

  Its objects are the rows of the list at its ``key``, each ``_default(data=row, parent=self)``, of the one class it
  makes them with; its steps start and stop them. With a ``poll_interval`` and objects, it refreshes them
  one at a time, each once per ``poll_interval``, starting ``poll_delay`` after it starts, in an order shuffled every
  round, passing the poller's keywords to each refresh.
  """
  key: str
  poll_interval: int
  poll_delay: int

  _task_group: asyncio.TaskGroup | None
  _background_tasks: set[asyncio.Task[Any]]
  _loop: asyncio.AbstractEventLoop | None
  _timer_ids = count(1)
  _default: ClassVar[type]   # .. the class of the objects it makes from the rows at its key

  def __init(self) -> None:
    self._task_group = None
    self._background_tasks = set()
    self._loop = None
    self.timers: dict[int, dict] = {}
    self.h_timeouts: dict[str, dict] = {}
    self._my_groups: list = []
    self._polled: list = []
    for data in glob_list(self.key): self._add_group(data)

  def _add_group(self, data: dict) -> None:
    self._my_groups.append(self._default(data=data, parent=self))

  def __start(self) -> None:
    for group in self._my_groups:
      if isinstance(group, AsyncApp): self._spawn(group.run())   # .. a row that is an app runs as one, on this app's loop
      else: group.start()
    if self.poll_interval and self._my_groups: self.run_every(self._cb_poller, start=self.poll_delay, interval=self.poll_interval / len(self._my_groups))

  def _cb_poller(self, **data: Any) -> None:
    if not self._polled: self._polled = random.sample(self._my_groups, len(self._my_groups))
    self._polled.pop().refresh(**data)

  def run_later(self, callback: Callable[..., Any], *, delay: int | float, key: str | None = None, **data: Any) -> Future:
    """``callback`` once, ``delay`` seconds from now; armed again under ``key``, the timer armed under it before is
    cancelled. Any thread arms it, and its handle's ``cancel()`` cancels it."""
    return self._timer(callback, float(delay), None, key, data)

  def run_every(self, callback: Callable[..., Any], *, start: int | float, interval: int | float, **data: Any) -> Future:
    """``callback`` ``start`` seconds from now, and again ``interval`` seconds after each run of it ends."""
    return self._timer(callback, float(start), float(interval), None, data)

  def _timer(self, callback: Callable[..., Any], delay: float, interval: float | None, key: str | None, data: dict) -> Future:
    # region - a timer is a coroutine on the app's loop
    # .. It keeps the app's registries itself, on the loop: its row is in `timers`, and under its key in `h_timeouts`,
    # .. while it is armed. Its callback runs on one of the loop's worker threads; one that raises is logged, and an
    # .. interval timer runs it again the next time. A one-shot is spent as it fires, so its key is free while its
    # .. callback runs.
    # endregion
    row = {'name': getattr(callback, '__name__', ''), 'kind': 'once' if interval is None else 'interval', 'interval': interval, 'next_run': now_ts() + delay}
    callback = _callback_wrapper(callback)

    async def call() -> None:
      try: await asyncio.to_thread(callback, **data)
      except Exception as error: self.Error('timer', row['name'], 'raised:', error)

    async def timer() -> None:
      row['task'], tid = asyncio.current_task(), next(self._timer_ids)
      if key in self.h_timeouts: self.h_timeouts[key]['task'].cancel()
      self.timers[tid] = row
      if key is not None: self.h_timeouts[key] = row
      try:
        await asyncio.sleep(delay)
        while interval is not None:
          await call()
          row['next_run'] = now_ts() + interval
          await asyncio.sleep(interval)
      finally:
        del self.timers[tid]
        if self.h_timeouts.get(key) is row: del self.h_timeouts[key]
      await call()

    return asyncio.run_coroutine_threadsafe(timer(), self._get_loop())

  def cancel_timers(self) -> None:
    """Every timer this app armed, cancelled, from any thread."""
    for row in list(self.timers.values()): row['task'].get_loop().call_soon_threadsafe(row['task'].cancel)

  def __stop(self) -> None:
    for group in self._my_groups: group.stop()
    self.cancel_timers()
    loop = self._loop
    if loop is None: return                    # .. not running: nothing it spawned is left to cancel
    # .. the loop cancels what the app spawned before it stopped, from any thread and from inside its own tasks: an MQTT
    # .. listener that stops its app ends the MQTT loop it runs in; what a later stop step spawns, as a cleanup, runs
    tasks = list(self._background_tasks)
    loop.call_soon_threadsafe(lambda: [task.cancel() for task in tasks])

  def schedule[T](self, coroutine: Coroutine[Any, Any, T], /) -> Future[T]:
    """``coroutine`` on the app's loop, from any thread; its standard future."""
    return asyncio.run_coroutine_threadsafe(coroutine, self._get_loop())

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    loop = self._loop
    if loop is None: raise RuntimeError(f'{self!r} is not running')
    return loop

  async def run(self) -> None:
    """init, load and start on this loop; returns when the app is stopped."""
    if self._task_group is not None: raise RuntimeError(f'{self!r} is already running')
    try:
      self._loop = asyncio.get_running_loop()
      async with asyncio.TaskGroup() as tasks:
        self._task_group = tasks
        for step in (self.init, self.load, self.start):
          if result := step(): await result
        if not self.stopped: self._spawn(asyncio.Event().wait())   # .. started, it runs until its stop step cancels what it spawned
    finally:
      self._task_group = None
      self._loop = None
      self._background_tasks.clear()

  def _spawn[T](self, coroutine: Coroutine[Any, Any, T], /) -> asyncio.Task[T]:
    if self._task_group is None: raise RuntimeError(f'{self!r} is not running')
    task = self._task_group.create_task(coroutine)
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
    return task
# endregion


# region MQTT: an async app's broker, the `mqtt` of its configuration
class mixin_Mqtt(YStart):
    """An async app's MQTT, two methods: ``mqtt_listen`` and ``mqtt_publish``. Its broker is the ``mqtt`` of its
    configuration, which the client takes as it is, all but ``status_topic``: the app's will is ``offline`` there, and it
    says ``online`` there as it connects. Its start step connects, on MQTT 5, and the client connects again 5 s after it
    loses the broker."""

    def __init(self) -> None:
        self._client: aiomqtt.Client | None = None
        self._callbacks: dict[y2topic, list[tuple[Callable[..., Any], Any, bool]]] = {}   # .. a topic's listeners: callback, payload, ignore_retained
        self._subscriptions: dict[y2topic, int] = {}                                    # .. a topic's QoS

    def __start(self) -> None: self._spawn(self._mqtt_loop())

    async def mqtt_listen(self, callback: Callable[..., Any], topic: y2topic | str, payload: Any = None, *, ignore_retained: bool = False, qos: int = 0) -> None:
        """``callback(topic, payload)``, sync or async, on each message at ``topic`` (MQTT's wildcards match), or only on
        those whose payload is ``payload``; with ``ignore_retained``, not on a message the broker kept."""
        topic = y2topic(topic)
        listeners = self._callbacks.setdefault(topic, [])
        if (callback, payload, ignore_retained) not in listeners: listeners.append((callback, payload, ignore_retained))
        if self._subscriptions.get(topic, -1) >= qos: return
        self._subscriptions[topic] = qos
        if self._client is not None: await self._client.subscribe(str(topic), qos=qos)

    async def mqtt_publish(self, topic: y2topic | str, payload: Any = '', *, retain: bool = False, qos: int = 0, expiry: int | None = None, **data: Any) -> None:
        """``payload`` at ``topic``, a dict or a list as JSON; ``expiry`` is MQTT 5's message expiry in seconds, and the
        other keywords its user properties. While the broker is lost, nothing is sent."""
        if self._client is None: return
        properties = Properties(PacketTypes.PUBLISH) if expiry is not None or data else None
        if expiry is not None: properties.MessageExpiryInterval = int(expiry)
        if data: properties.UserProperty = [(key, str(value)) for key, value in data.items()]
        payload = json.dumps(payload) if isinstance(payload, (dict, list)) else payload if isinstance(payload, bytes) else str(payload)
        await self._client.publish(str(topic), payload, qos=qos, retain=retain, properties=properties)

    async def _mqtt_loop(self) -> None:
        options = dict(self.my_dict('mqtt'))
        status = options.pop('status_topic')
        while True:
            try:
                async with aiomqtt.Client(**options, protocol=aiomqtt.ProtocolVersion.V5, will=aiomqtt.Will(status, b'offline', qos=1, retain=True)) as self._client:
                    self.Info('connected to the broker')
                    for topic, qos in list(self._subscriptions.items()): await self._client.subscribe(str(topic), qos=qos)
                    await self._client.publish(status, 'online', qos=1, retain=True)
                    async for message in self._client.messages: await self._mqtt_message(message)
            except aiomqtt.MqttError as error: self.Warn('lost the broker, connecting again in 5 s:', error)
            self._client = None
            await asyncio.sleep(5)

    async def _mqtt_message(self, message: aiomqtt.Message) -> None:
        payload = message.payload.decode(errors='replace') if isinstance(message.payload, bytes) else message.payload
        if isinstance(payload, str) and payload[:1] in ('{', '['):
            try: payload = json.loads(payload)
            except json.JSONDecodeError: pass   # .. not JSON after all: the text is the payload
        for topic, listeners in list(self._callbacks.items()):
            if not message.topic.matches(str(topic)): continue
            for callback, expected, ignore_retained in list(listeners):
                if (ignore_retained and message.retain) or expected not in (None, payload): continue
                try:
                    if inspect.isawaitable(result := callback(y2topic(str(message.topic)), payload)): await result
                except Exception as error: self.Error('listener failed:', message.topic, error)   # .. one listener's failure stops neither the others nor the app


class AppService(mixin_Mqtt, AsyncApp):
    """An app whose part of Env arrives over MQTT: ``config_mqtt/topics`` in its own configuration maps each retained topic
    to the path in Env that its payload replaces, filled as Env's file is, so ``glob`` reads it as it reads the rest of
    Env. An app that acts on new configuration listens to the same topic: its listener runs after the section is loaded.
    ``await app.from_mqtt()`` reads every topic once, then stops."""

    def __init(self) -> None:
        self.until_loaded: set[str] | None = None   # .. from_mqtt: the topics still to arrive

    async def from_mqtt(self) -> None:
        """Each of its topics read once, then the app stopped."""
        self.until_loaded = set(self.my_dict('config_mqtt/topics'))
        await self.run()

    @sync
    async def __load(self) -> None:
        for topic in self.my_dict('config_mqtt/topics'): await self.mqtt_listen(self._receive_config, topic, qos=1)

    def _receive_config(self, topic: y2topic, payload: Any) -> None:
        deepset(self.my('config_mqtt/topics')[str(topic)], Env.data, yaml.load(payload, Loader=YmlLoader) if isinstance(payload, str) else payload)
        Env.data = jinja.configuration(Env.data)   # .. the section that arrived is filled as Env's file was, with what Env holds
        if self.until_loaded is not None:
            self.until_loaded.discard(str(topic))
            if not self.until_loaded: self.stop()
# endregion






# region REST surface
class mixin_Rest:
  """Deprecated: it does not work and gets in the way. Its one user is Y2's UI API, whose object pages and entity
  command buttons go through it, so it stays until they move off it.

  Every public member of the application's own classes, over HTTP, and nothing
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
