"""gppu.iot — devices and the broker: entity names, device controls, MQTT, the Y2 lifecycle.

y2slug and y2eid name an entity; SerializedControl runs a device's coroutines on one daemon loop, one at a time per
instance, for synchronous callers; HTTPControl and JSONHTTPControl make a request each. Mqtt is a broker Connection and MqttApp an app whose lifecycle holds one.
_YMRO and its steps are the Y2 init→load→start→stop lifecycle.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import ssl
import threading
from abc import abstractmethod
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from concurrent.futures import Future
from fnmatch import fnmatchcase
from typing import Any, ClassVar, Optional, final

import aiohttp
import aiomqtt
import yaml
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from gppu import AsyncApp, Env, EventLoopBridge, Info, Provider, Warn, _Base, _DC, jinja_template
from gppu.app import AsyncSubmission
from gppu.gppu import _DC_BASE_TYPE_MAP, Debug, y2list, y2path, y2topic, y2uri


# region y2eid
class y2slug(y2list):
  def __init__(self, o):
    self.token = '_'

    if '@' in str(o): o = str(o).split('@')[0]
    self.data = self._any2list(o)

class y2eid:
  ns: str
  domain: str
  slug: y2slug
  default_ns: ClassVar[str] = 'yala'
  default_domain: ClassVar[str] = 'entity'
  _ready: bool = False

  def __bool__(self) -> bool: return self._ready

  def __init__(self, o: Any, ns: Optional[str] = None, **kw):
    self._ready = False
    if not o: raise ValueError("y2eid: empty input")
    ns = ns or self.default_ns
    if isinstance(o, y2eid): s = str(o)
    elif isinstance(o, dict): s = str(o.get('entity_id', ""))
    elif isinstance(o, str): s = o
    elif hasattr(o, 'entity_id') and hasattr(o, 'namespace'): s = f"{o.entity_id}@{o.namespace}"
    elif hasattr(o, 'entity_id') and hasattr(o, 'ns'): s = f"{o.entity_id}@{o.ns}"
    elif hasattr(o, 'seid'): s = o.seid
    else: raise ValueError
    self.ns = ns
    self.domain = ''
    if '.' in s: self.domain, s = s.split('.', 1)
    if '@' in s: s, self.ns = s.rsplit('@', 1)
    self.ns = self.ns or self.default_ns
    self.domain = self.domain or self.default_domain
    self.slug = y2slug(s)
    for k in ['tail', 'head']: setattr(self, k, getattr(self.slug, k))
    self._ready = True

  def __str__(self):
    s = str(self.slug)
    if self.domain: s = self.domain + '.' + s
    if self.ns: s += '@' + self.ns
    return s
  def __repr__(self): return str(self)
  def __hash__(self): return hash(str(self))
  def __eq__(self, other): return str(self) == str(other)
  def __lt__(self, other): return str(self) < str(other)

  def endswith(self, ix) -> bool: return self.slug.endswith(ix)
  def startswith(self, ix) -> bool: return self.slug.startswith(ix)
  @property
  def entity_id(self) -> str: return f"{self.domain}.{self.slug}" if self._ready else ""
  @property
  def seid(self): return str(self)
# endregion


_DC_BASE_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic, 'y2path': y2path, 'y2uri': y2uri}
_DC._DC_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic, 'y2path': y2path, 'y2uri': y2uri}



# $$
# $$        Serialized controls
# $$
class SerializedControl(EventLoopBridge):
  """Runs controls on one daemon loop, serialized by a per-instance lock."""

  _control_loop: ClassVar[asyncio.AbstractEventLoop | None] = None
  _control_loop_start_lock: ClassVar[threading.Lock] = threading.Lock()
  _control_lock: asyncio.Lock | None = None

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    loop = SerializedControl._control_loop
    if loop is not None: return loop

    with SerializedControl._control_loop_start_lock:
      loop = SerializedControl._control_loop
      if loop is None:
        ready = Future[asyncio.AbstractEventLoop]()
        threading.Thread(target=SerializedControl._run_loop, args=(ready,), daemon=True, name='gppu-controls').start()
        SerializedControl._control_loop = loop = ready.result()
    return loop

  @staticmethod
  def _run_loop(ready: Future[asyncio.AbstractEventLoop]) -> None:
    async def main() -> None:
      ready.set_result(asyncio.get_running_loop())
      await asyncio.Event().wait()

    try: asyncio.run(main())
    except BaseException as error:
      if ready.done(): raise
      ready.set_exception(error)

  def _control_call[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    return self.call(self._control_run, function, *args, **kwargs)

  def _control_submit[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> AsyncSubmission[T]:
    return self.submit(self._control_run, function, *args, **kwargs)

  async def _control_run[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    lock = self._control_lock
    if lock is None: lock = self._control_lock = asyncio.Lock()
    async with lock: return await function(*args, **kwargs)


# $$
# $$        HTTP and JSON-over-HTTP controls
# $$
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type HttpBody = str | bytes


class HTTPControl(SerializedControl):
  """Serialized textual HTTP; returns ``None`` on request or response failure."""

  _http_timeout: float = 10
  _http_headers: Mapping[str, str] | None = None
  _http_ssl: ssl.SSLContext | bool | None = None

  def _http_get(self, url: str, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._http_request('GET', url, headers=headers)

  def _http_put(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._http_request('PUT', url, body, headers=headers)

  def _http_post(self, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._http_request('POST', url, body, headers=headers)

  def _http_request(self, method: str, url: str, body: HttpBody | None = None, *, headers: Mapping[str, str] | None = None) -> str | None:
    return self._control_call(self._http_request_async, method, url, body, headers)

  async def _http_request_async(self, method: str, url: str, body: HttpBody | None = None, headers: Mapping[str, str] | None = None) -> str | None:
    request_headers = {**(self._http_headers or {}), **(headers or {})} or None
    try:
      timeout = aiohttp.ClientTimeout(total=self._http_timeout)
      async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, data=body, headers=request_headers, ssl=self._http_ssl) as response:
          response.raise_for_status()
          return await response.text()
    except (aiohttp.ClientError, TimeoutError, OSError, UnicodeError):
      return None


_NO_JSON_BODY = object()


class JSONHTTPControl(HTTPControl):
  """Explicit JSON request/response layer over ``HTTPControl``."""

  def _json_get(self, url: str, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('GET', url, headers=headers)

  def _json_put(self, url: str, payload: JsonValue, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('PUT', url, payload, headers=headers)

  def _json_post(self, url: str, payload: JsonValue, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._json_request('POST', url, payload, headers=headers)

  def _json_request(self, method: str, url: str, payload: JsonValue | object = _NO_JSON_BODY, *, headers: Mapping[str, str] | None = None) -> JsonValue:
    return self._control_call(self._json_request_async, method, url, payload, headers)

  async def _json_request_async(self, method: str, url: str, payload: JsonValue | object = _NO_JSON_BODY, headers: Mapping[str, str] | None = None) -> JsonValue:
    request_headers = {'Accept': 'application/json', **(headers or {})}
    body = None
    if payload is not _NO_JSON_BODY:
      request_headers.setdefault('Content-Type', 'application/json')
      body = json.dumps(payload)
    response = await self._http_request_async(method, url, body, request_headers)
    if response is None: return None
    try: return json.loads(response)
    except json.JSONDecodeError: return None


type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type MqttPayload = JsonValue | bytes
type MqttCallback = Callable[[y2topic, object], object | Awaitable[object]]


class Mqtt(Provider):
  """One broker connection: ``hostname``, ``port``, ``username``, ``password``, ``identifier``, ``status_topic``.

  ``listen`` and ``config`` register before or after ``serve``; subscriptions are replayed on every reconnect.
  ``connected`` is set while a client is up, ``configured`` once every ``config`` topic has delivered. Callbacks take ``(topic, payload)``, may be sync or async, and run one
  at a time; a JSON payload arrives parsed.
  """
  scheme = 'mqtt'
  CLIENT_KEYS = ('hostname', 'port', 'username', 'password', 'identifier')
  RECONNECT_DELAY = 5
  PROTOCOL: Any = None

  def __init__(self, connection=None, uid: str = '') -> None:
    super().__init__(connection, uid)
    self.connected = asyncio.Event()
    self._client: aiomqtt.Client | None = None
    self._tasks: asyncio.TaskGroup | None = None
    self._session: asyncio.TaskGroup | None = None
    self._while_connected: list[Callable[[], Awaitable[Any]]] = []
    self._callbacks: dict[y2topic, list[tuple[MqttCallback, object, bool, bool]]] = {}
    self._subscriptions: dict[y2topic, int] = {}
    self._config_paths: dict[str, str] = {}
    self._config_pending: set[str] = set()
    self.configured = asyncio.Event()
    self._lock = asyncio.Lock()
    self._callback_lock = asyncio.Lock()

  # -- the connection ----------------------------------------------------------------------
  async def serve(self) -> None:
    """Hold the connection, reconnecting, and deliver messages to the listeners; run it with the app's ``_spawn``.
    Callbacks run in a TaskGroup that outlives each connection, so a reconnect never cancels one mid-way; a callback
    registered with ``raise_errors`` that raises ends ``serve`` with its error."""
    if self._tasks is not None: raise RuntimeError(f'{self!r} is already serving')
    try:
      async with asyncio.TaskGroup() as tasks:
        self._tasks = tasks
        while True:
          await self._connect_once()
          await asyncio.sleep(self.RECONNECT_DELAY)
    finally:
      self._tasks = None

  async def _connect_once(self) -> None:
    status = self.connection['status_topic'] if 'status_topic' in self.connection else ''
    try:
      async with self._client_for(status) as client:
        self._client = client
        try:
          Info('connected:', self.connection['hostname'], self.connection.get('port'))
          async with self._lock: subscriptions = tuple(self._subscriptions.items())
          for topic, qos in subscriptions: await client.subscribe(str(topic), qos=qos)
          if status: await client.publish(status, 'online', qos=1, retain=True)
          self.connected.set()
          async with asyncio.TaskGroup() as session:
            self._session = session
            for factory in self._while_connected: session.create_task(factory())
            await self._dispatch(client)
        finally:
          self._session = None
          self.connected.clear()
          self._client = None
          if status:
            try: await client.publish(status, 'offline', qos=1, retain=True)   # a clean DISCONNECT does not fire the will
            except aiomqtt.MqttError: pass
    except* aiomqtt.MqttError as errors:
      Warn(f'mqtt error, reconnect in {self.RECONNECT_DELAY}s:', *errors.exceptions)

  def _client_for(self, status: str) -> aiomqtt.Client:
    options = {key: self.connection[key] for key in self.CLIENT_KEYS if key in self.connection}
    if self.PROTOCOL is not None: options['protocol'] = self.PROTOCOL
    if status: options['will'] = aiomqtt.Will(topic=status, payload=b'offline', qos=1, retain=True)
    return aiomqtt.Client(**options)

  async def _dispatch(self, client: aiomqtt.Client) -> None:
    async for message in client.messages:
      topic = str(message.topic)
      raw = message.payload.decode(errors='replace') if isinstance(message.payload, bytes) else str(message.payload)
      payload: object = raw
      if raw.lstrip()[:1] in '[{':
        try: payload = json.loads(raw)
        except json.JSONDecodeError: pass

      async with self._lock:
        callbacks = [(callback, raise_errors, raw) for pattern, entries in self._callbacks.items()
                     if topic_matches(topic, str(pattern))
                     for callback, expected, ignore_retained, raise_errors, raw in entries
                     if not (ignore_retained and message.retain) and (expected is None or expected == payload)]
      for callback, raise_errors, raw in callbacks:
        if raw:
          result = callback(message)
          if inspect.isawaitable(result): await result
        else: self._tasks.create_task(self._callback(callback, y2topic(topic), payload, raise_errors))

  async def _callback(self, callback: MqttCallback, topic: y2topic, payload: object, raise_errors: bool) -> None:
    async with self._callback_lock:
      try:
        result = callback(topic, payload)
        if inspect.isawaitable(result): await result
      except Exception as error:
        if raise_errors: raise
        Warn('callback error:', topic, error)

  # -- what an app does with it ------------------------------------------------------------
  async def listen(self, callback: MqttCallback, topic: y2topic | str, payload: object = None, *,
                   ignore_retained: bool = False, raise_errors: bool = False, qos: int = 0, raw: bool = False) -> None:
    """Call callback for messages on topic (wildcards allowed), only those equal to payload when it is given.

    With ``raw``, callback receives the aiomqtt message itself (bytes, retain, MQTT 5 properties) and is awaited in
    the dispatch loop, in arrival order: what a recorder of the wire needs, at the rate of the wire."""
    topic = y2topic(topic)
    async with self._lock:
      entries = self._callbacks.setdefault(topic, [])
      entry = (callback, payload, ignore_retained, raise_errors, raw)
      if entry not in entries: entries.append(entry)
      old_qos = self._subscriptions[topic] if topic in self._subscriptions else -1
      qos = max(old_qos, qos)
      self._subscriptions[topic] = qos
      client = self._client if qos != old_qos else None
    if client is not None: await client.subscribe(str(topic), qos=qos)

  def while_connected(self, factory: Callable[[], Awaitable[Any]]) -> None:
    """Run ``factory()`` on every connection: started once connected, cancelled when the connection drops. An
    ``MqttError`` it raises drops the connection, which reconnects; any other error ends ``serve``."""
    self._while_connected.append(factory)
    if self._session is not None: self._session.create_task(factory())

  async def publish(self, topic: y2topic | str, payload: MqttPayload = '', *, retain: bool = False, qos: int = 0,
                    expiry: int | None = None, **properties: Any) -> None:
    """Publish; a dict or list goes as JSON, keyword properties as MQTT 5 user properties. Discarded while
    disconnected."""
    client = self._client
    if client is None: return
    if isinstance(payload, (dict, list)): wire = json.dumps(payload)
    elif isinstance(payload, bytes): wire = payload
    else: wire = str(payload)
    props = None
    if expiry is not None or properties:
      props = Properties(PacketTypes.PUBLISH)
      if expiry is not None: props.MessageExpiryInterval = int(expiry)
      if properties: props.UserProperty = [(key, str(value)) for key, value in properties.items()]
    await client.publish(str(topic), wire, qos=qos, retain=retain, properties=props)

  async def config(self, topics: dict[str, str], *, wait: bool = False) -> None:
    """Receive configuration into Env: each exact topic carries a YAML or JSON mapping for one Env slash path (empty
    for the root). ``Env.on_change`` reports what arrives. With ``wait``, return once every topic has delivered, which
    needs ``serve`` running; bound it with ``asyncio.timeout``."""
    if not Env.initialized: raise RuntimeError('load the bootstrap configuration with Env.from_env() first')
    self._config_paths = config_topics(self._config_paths | config_topics(topics))
    self._config_pending |= set(topics)
    self.configured.clear()
    for topic in topics: await self.listen(self._receive_config, topic, qos=1, raise_errors=True)
    if wait: await self.configured.wait()

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    data = yaml.safe_load(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict): raise TypeError(f'MQTT configuration must be a mapping: {topic}')
    Env.update_config(data, self._config_paths[str(topic)])
    self._config_pending.discard(str(topic))
    if not self._config_pending: self.configured.set()


class Mqtt5(Mqtt):
  """MQTT 5: message expiry and user properties."""
  PROTOCOL = aiomqtt.ProtocolVersion.V5


class MqttApp(AsyncApp):
  """An AsyncApp whose lifecycle holds its broker: the ``connection`` row of the app's configuration table.

  Before ``main`` runs, the lifecycle builds ``self.mqtt`` from that row, receives the configuration its ``config``
  topics carry into Env, connects, and publishes online when the row has a ``status_topic`` (the will then publishes
  offline if the process dies). A row's Jinja renders with the app's ``host``, so one row serves every host. ``wait``
  bounds, in seconds, how long ``main`` waits to be connected and configured; without it, ``main`` waits until it is.
  ``main`` prepares what the app needs and spawns lasting work, and may await ``self.serving`` to last as long as the
  connection; when it returns, ``on_message`` is subscribed to the row's ``listen`` topics. The connection is kept,
  reconnecting, until the app stops. An app that only reacts to its configured topics writes ``on_message`` and
  nothing else.

      recorder:
        connection: {hostname: mqtt, port: 1883, identifier: recorder, status_topic: status/recorder, listen: ['#']}
      panel:
        connection: {hostname: mqtt, status_topic: 'status/panel/{{ host }}', wait: 5, config: {panel/config/scenes: panel/scenes}}

      class Recorder(MqttApp):
        raw = True
        def on_message(self, message) -> None: ...

  ``mqtt_class`` is the Provider (Mqtt5 for MQTT 5). ``on_message`` takes ``(topic, payload)``, or the aiomqtt
  message itself when ``raw`` (bytes, retain, MQTT 5 properties, in arrival order); ``qos`` is the listen topics'.
  """
  mqtt_class: type[Mqtt] = Mqtt
  raw = False
  qos = 0
  mqtt: Mqtt
  serving: asyncio.Task

  async def main(self) -> None: pass

  def on_message(self, *message: Any) -> Any: raise NotImplementedError(f'{type(self).__name__} listens but defines no on_message')

  async def invoke(self, **given: Any) -> Any:
    params = self.params(**given)
    row = {key: jinja_template(value, host=self.host) if isinstance(value, str) and '{{' in value else value
           for key, value in self.my('connection').items()}
    self.mqtt = self.mqtt_class(row)
    async with self._task_scope():
      if 'config' in row: await self.mqtt.config(row['config'])
      self.serving = self._spawn(self.mqtt.serve())
      await self._ready(row)
      result = await self.call_main(params)
      for topic in row['listen'] if 'listen' in row else ():
        await self.mqtt.listen(self.on_message, topic, qos=self.qos, raw=self.raw)
      return result

  async def _ready(self, row: dict) -> None:
    """Connected and configured; past the row's ``wait``, main runs on what has arrived and the rest applies live."""
    async def ready() -> None:
      await self.mqtt.connected.wait()
      if 'config' in row: await self.mqtt.configured.wait()
    if 'wait' not in row: return await ready()
    try:
      async with asyncio.timeout(row['wait']): await ready()
    except TimeoutError:
      self.Warn('after', row['wait'], 's:', 'configuration incomplete' if self.mqtt.connected.is_set() else 'broker unreachable')

def topic_matches(topic: str, pattern: str) -> bool:
  """MQTT filter matching: ``+`` one level, ``#`` the rest; ``$`` topics only by a ``$`` pattern. A level holding ``*``
  globs that level (``brultech/01122089_*``), for filters applied here, such as an exclude list: the broker takes it as
  a literal, so it matches no more than a subscription would."""
  if topic.startswith('$') and not pattern.startswith('$'): return False
  topic_parts, pattern_parts = topic.split('/'), pattern.split('/')
  for index, expected in enumerate(pattern_parts):
    if expected == '#': return index == len(pattern_parts) - 1
    if index == len(topic_parts): return False
    if expected == '+' or expected == topic_parts[index]: continue
    if '*' not in expected or not fnmatchcase(topic_parts[index], expected): return False
  return len(topic_parts) == len(pattern_parts)


def config_topics(topics: dict[str, str]) -> dict[str, str]:
  """Validate a topic → Env path map: exact topics, slash paths, no path inside another."""
  if not isinstance(topics, dict) or not topics: raise ValueError('MQTT configuration requires a topic to Env path mapping')
  paths: list[str] = []
  for topic, path in topics.items():
    if not isinstance(topic, str) or not topic or '+' in topic or '#' in topic:
      raise ValueError('MQTT configuration topics must be exact topic names')
    if not isinstance(path, str) or (path and any(not part for part in path.split('/'))):
      raise ValueError('MQTT configuration paths must be slash paths or empty for the root')
    if any(not path or not other or path == other or path.startswith(other + '/') or other.startswith(path + '/') for other in paths):
      raise ValueError('MQTT configuration paths must not overlap')
    paths.append(path)
  return dict(topics)


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
