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
from typing import Any, ClassVar

import aiomqtt
import yaml
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from .gppu import App, Env, YmlLoader, _Base, _DC, _mixin, deepset, glob_dict, glob_list, jinja, now_ts, sync, y2topic
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
  """An app on asyncio: ``asyncio.run(MyApp().run())``. Construction runs its init step; ``run()`` runs its load and
  start steps on the loop, and it runs until ``stop()``. A class gives its part of a step as a private ``__init``,
  ``__load``, ``__start`` or ``__stop``; every class's part runs, base first.
  """

  def __init(self) -> None:
    self._loop: asyncio.AbstractEventLoop | None = None
    self._task_group: asyncio.TaskGroup | None = None
    self._background_tasks: set[asyncio.Task] = set()

  def __stop(self) -> None:
    if self._loop is None: return   # .. not running: nothing it spawned is left to cancel
    tasks = list(self._background_tasks)   # .. what it spawned before it stopped; a cleanup a later stop step spawns runs
    self._loop.call_soon_threadsafe(lambda: [task.cancel() for task in tasks])

  def schedule[T](self, coroutine: Coroutine[Any, Any, T], /) -> Future[T]:
    """``coroutine`` on the app's loop, from any thread; its standard future."""
    return asyncio.run_coroutine_threadsafe(coroutine, self._get_loop())

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    if self._loop is None: raise RuntimeError(f'{self!r} is not running')
    return self._loop

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


# region Timers: an async app's run_later and run_every
class mixin_Timers(YStart):
  """``run_later`` and ``run_every`` on its async app's loop. ``timers`` holds every armed timer's row by its id (its
  callback's name, its kind, its interval and its next run), ``h_timeouts`` those armed under a key."""

  def __init(self) -> None:
    self.timers: dict[int, dict] = {}
    self.h_timeouts: dict[str, dict] = {}

  def __stop(self) -> None: self.cancel_timers()

  def run_later(self, callback: Callable[..., Any], *, delay: int | float, key: str | None = None, **data: Any) -> Future:
    """``callback`` once, ``delay`` seconds from now; armed again under ``key``, the one armed under it before is
    cancelled. Any thread arms it; its handle's ``cancel()`` cancels it."""
    return self.schedule(self._timer(callback, float(delay), None, key, data))

  def run_every(self, callback: Callable[..., Any], *, start: int | float, interval: int | float, **data: Any) -> Future:
    """``callback`` ``start`` seconds from now, and again ``interval`` seconds after each run of it ends."""
    return self.schedule(self._timer(callback, float(start), float(interval), None, data))

  async def _timer(self, callback: Callable[..., Any], delay: float, interval: float | None, key: str | None, data: dict) -> None:
    # .. its row is in `timers`, and under its key in `h_timeouts`, while it is armed; its callback runs off the loop
    row = {'name': getattr(callback, '__name__', ''), 'kind': 'once' if interval is None else 'interval', 'interval': interval,
           'next_run': now_ts() + delay, 'task': asyncio.current_task()}
    if key in self.h_timeouts: self.h_timeouts[key]['task'].cancel()
    self.timers[id(row)] = row
    if key is not None: self.h_timeouts[key] = row
    callback = _callback_wrapper(callback)
    try:
      while True:
        await asyncio.sleep(row['next_run'] - now_ts())
        if interval is None:   # .. a one-shot is spent as it fires: its key is free while its callback runs
          del self.timers[id(row)]
          if self.h_timeouts.get(key) is row: del self.h_timeouts[key]
        try: await asyncio.to_thread(callback, **data)
        except Exception as error: self.Error('timer', row['name'], 'raised:', error)
        if interval is None: return
        row['next_run'] = now_ts() + interval
    finally:
      self.timers.pop(id(row), None)
      if self.h_timeouts.get(key) is row: del self.h_timeouts[key]

  def cancel_timers(self) -> None:
    """Every timer this app armed, cancelled, from any thread."""
    for row in list(self.timers.values()): row['task'].get_loop().call_soon_threadsafe(row['task'].cancel)
# endregion


# region Groups: an app's objects, the rows at its key
class mixin_Groups(mixin_Timers):
  """An async app's objects are the rows at its ``key``, each made as the class the row names in ``class``, among
  ``_default`` and its subclasses, or as ``_default``; a row that is an app runs as one. With a ``poll_interval``, each
  is refreshed on it, at least once an hour, their first refreshes spread over one interval in shuffled order."""
  key: str
  poll_interval: int
  _default: ClassVar[type]

  def __init(self) -> None:
    self._my_groups: list = []
    for data in glob_list(self.key): self._add_group(data)

  def _add_group(self, data: dict) -> None:
    cls = self._default
    if 'class' in data:   # .. the class it names exactly, among the default class and its subclasses
      family, classes = [self._default], {}
      while family:
        named = family.pop()
        classes[named.__name__] = named
        family += named.__subclasses__()
      cls = classes[data['class']]
    self._my_groups.append(cls(data=data, parent=self))

  def __start(self) -> None:
    for group in self._my_groups:
      if isinstance(group, AsyncApp): self._spawn(group.run())   # .. a row that is an app runs as one, on this app's loop
      else: group.start()
    if self.poll_interval:
      for i, group in enumerate(random.sample(self._my_groups, len(self._my_groups))):
        self.run_every(group.refresh, start=i * self.poll_interval / len(self._my_groups), interval=min(self.poll_interval, 3600))

  def __stop(self) -> None:
    for group in self._my_groups: group.stop()
# endregion


# region MQTT: an async app's broker, the `mqtt` of its configuration
class mixin_Mqtt(YStart):

    def __init(self) -> None:
        self._client: aiomqtt.Client | None = None
        self._callbacks: dict[y2topic, list[tuple[Callable[..., Any], Any, bool]]] = {}   # .. a topic's listeners: callback, payload, ignore_retained
        self._subscriptions: dict[y2topic, int] = {}                                    # .. a topic's QoS
        self._retained: dict[int, tuple[tuple, set[str]]] = {}   # .. a listener by id: it (held, so its id stays its own) and the topics whose retained message it got on this connection

    def __start(self) -> None: self._spawn(self._mqtt_loop())

    async def mqtt_listen(self, callback: Callable[..., Any], topic: y2topic | str, payload: Any = None, *, ignore_retained: bool = False, qos: int = 0) -> None:
        """``callback(topic, payload)``, sync or async, on each message at ``topic`` (MQTT's wildcards match), or only on
        those whose payload is ``payload``; with ``ignore_retained``, not on a message the broker kept. A callback that
        takes ``retained`` or ``sent`` is also told whether the broker kept the message and when it was sent, in epoch
        seconds (None where its publisher did not say; ``mqtt_publish`` always does). Each listener gets a topic's retained
        messages once, however many listeners the topic had before it."""
        topic = y2topic(topic)
        listener = (callback, payload, ignore_retained)
        listeners = self._callbacks.setdefault(topic, [])
        if listener in listeners and self._subscriptions[topic] >= qos: return
        if listener not in listeners: listeners.append(listener)
        self._subscriptions[topic] = max(qos, self._subscriptions.get(topic, 0))
        # .. every subscribe has the broker send the topic's retained messages again, and they reach only the listeners they have not reached
        if self._client is not None: await self._client.subscribe(str(topic), qos=self._subscriptions[topic])

    async def mqtt_publish(self, topic: y2topic | str, payload: Any = '', *, retain: bool = False, qos: int = 0, expiry: int | None = None, **data: Any) -> None:
        """``payload`` at ``topic``, a dict or a list as JSON; ``expiry`` is MQTT 5's message expiry in seconds, and the
        other keywords its user properties, after ``sent``, the time it is sent. While the broker is lost, nothing is sent."""
        if self._client is None: return
        properties = Properties(PacketTypes.PUBLISH)
        properties.UserProperty = [('sent', str(now_ts())), *((key, str(value)) for key, value in data.items())]
        if expiry is not None: properties.MessageExpiryInterval = int(expiry)
        payload = json.dumps(payload) if isinstance(payload, (dict, list)) else payload if isinstance(payload, bytes) else str(payload)
        await self._client.publish(str(topic), payload, qos=qos, retain=retain, properties=properties)

    async def _mqtt_loop(self) -> None:
        mqtt = self.my('mqtt') or glob_dict('mqtt')   # .. its connection: its own, as the any2mqtt services have, or the environment's
        will = aiomqtt.Will(mqtt['status_topic'], b'offline', qos=1, retain=True) if 'status_topic' in mqtt else None
        while True:
            try:
                async with aiomqtt.Client(**{key: mqtt[key] for key in ('hostname', 'port', 'username', 'password', 'identifier') if key in mqtt}, protocol=aiomqtt.ProtocolVersion.V5, will=will) as self._client:
                    self.Info('connected to the broker')
                    self._retained.clear()   # .. a new connection sends every listener the retained messages again
                    for topic, qos in list(self._subscriptions.items()): await self._client.subscribe(str(topic), qos=qos)
                    if will: await self._client.publish(will.topic, 'online', qos=1, retain=True)
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
            for listener in list(listeners):
                callback, expected, ignore_retained = listener
                if expected not in (None, payload): continue
                if message.retain:
                    if ignore_retained: continue
                    got = self._retained.setdefault(id(listener), (listener, set()))[1]
                    if str(message.topic) in got: continue
                    got.add(str(message.topic))
                try:
                    sent = next((float(value) for key, value in getattr(message.properties, 'UserProperty', None) or [] if key == 'sent'), None)
                    if inspect.isawaitable(result := _callback_wrapper(callback)(y2topic(str(message.topic)), payload, retained=message.retain, sent=sent)): await result
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
        self.until_loaded = set(self.my('config_mqtt/topics'))
        await self.run()

    async def __load(self) -> None:
        for topic in self.my('config_mqtt/topics'): await self.mqtt_listen(self._receive_config, topic, qos=1)

    def _receive_config(self, topic: y2topic, payload: Any) -> None:
        deepset(self.my('config_mqtt/topics')[str(topic)], Env.data, yaml.load(payload, Loader=YmlLoader) if isinstance(payload, str) else payload)
        Env.data = jinja.configuration(Env.data)   # .. the section that arrived is filled as Env's file was, with what Env holds
        if self.until_loaded is not None:
            self.until_loaded.discard(str(topic))
            if not self.until_loaded: self.stop()
# endregion






# region REST surface
class mixin_Rest:
  ## !! Deviated from simple class to provide rest (put/post/get etc
  """Every public member of the application's own classes over HTTP, and nothing declared. A GET reads an object, a
  field or property, or a method that needs nothing; a POST calls a method with the JSON body as its keyword arguments.
  A name is the application's when a class born in the application's folder, the folder of the file that defines the
  app, defines it, a base may define it too; the private names and the lifecycle steps are the only exclusion. The app
  that serves it finds the object by its id and answers with the ``(payload, status)`` these return."""
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
      self._rest_manifest = {'classes': {n: c for n, c in classes.items() if c['members']}}
    return self._rest_manifest

  def _rest_rows(self, obj) -> dict[str, dict]:
    return self.rest_manifest['classes'].get(type(obj).__name__, {}).get('members', {})

  def rest_read(self, obj, name: str | None = None) -> tuple[dict, int]:
    # !! Unnecessary overcomplication. Eliminate
    """GET: the object, what it holds and what it can be asked to do, or one of its members. Values only are read for the
    object: calling a method to build it would run it for anyone listing the objects."""
    rows = self._rest_rows(obj)
    if name is None: return {'class': type(obj).__name__, 'members': {n: getattr(obj, n) for n, r in rows.items() if r['kind'] == 'value'},
                             'methods': {n: r['args'] for n, r in rows.items() if r['kind'] == 'method'}}, 200
    if name not in rows: return {'success': False, 'error': f'{type(obj).__name__} has no {name!r}'}, 404
    if rows[name]['kind'] == 'method' and not rows[name]['read']: return {'success': False, 'error': f'{name} takes arguments; POST it'}, 405
    return {name: getattr(obj, name)() if rows[name]['kind'] == 'method' else getattr(obj, name)}, 200

  async def rest_call(self, obj, name: str, body: Mapping) -> tuple[dict, int]:
    # !! Unnecessary overcomplication. Eliminate
    """POST: the method called with the body as its keyword arguments."""
    row = self._rest_rows(obj).get(name)
    if row is None or row['kind'] != 'method': return {'success': False, 'error': f'{name} is not a method'}, 405
    method, args = getattr(obj, name), dict(body)
    if row['async']: result = await method(**args)
    else: result = await asyncio.get_running_loop().run_in_executor(None, lambda: method(**args))
    return {'success': True, 'result': result}, 200
# endregion
