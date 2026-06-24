"""IoT value types, MQTT transport, and serialized async controls.

``MqttApp`` serves standalone asyncio services. ``mixin_Mqtt`` is the same
transport without lifecycle ownership, used by Y2. Controls bridge synchronous
callers to one dedicated event-loop thread and serialize each device instance.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
import ssl
import threading

from collections import UserList
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Mapping
from concurrent.futures import Future
from typing import Any, ClassVar, List, Optional

try:
  import aiomqtt
  from paho.mqtt.packettypes import PacketTypes
  from paho.mqtt.properties import Properties
except ImportError:
  aiomqtt = None  # type: ignore[assignment]
  PacketTypes = None  # type: ignore[assignment]
  Properties = None  # type: ignore[assignment]
try:
  import aiohttp
except ImportError:
  aiohttp = None  # type: ignore[assignment]
from .app import AsyncApp
from .gppu import _DC, _DC_BASE_TYPE_MAP


# region y2xxx
# xx
# xx y2list, y2path and y2slug
# xx
""" y2list-based: y2path, y2slug"""
class y2list(UserList):
  data: List[Any]
  token: str


  def _any2list(self, o) -> list:
    result = []
    if o:
      if hasattr(o, 'data'): o = o.data
      if isinstance(o, (list, tuple)): result = [_ for _ in o if _]
      elif self.token: result = str(o).split(self.token)
      else: result = re.findall('[a-zA-Z0-9]+', str(o))
    return result


  def __init__(self, o: Optional[Any] = None) -> None:
    super().__init__()
    self.token = ""
    self.data = self._any2list(o)


  def __str__(self): return self.token.join(self.data)
  def __repr__(self): return self.token.join(self.data)
  def __eq__(self, other: Any) -> bool:
    if hasattr(other, 'data'): return self.data == other.data
    else: return str(self) == str(other)
  def __hash__(self): return hash(str(self))  # type: ignore


  def upper(self): return str(self).upper()
  def lower(self): return str(self).lower()
  def encode(self, encoding='utf-8', errors='strict'): return str(self.data).encode(encoding, errors)
  def iadd(self, o): self.data += self._any2list(o)
  def to_json(self): return str(self)


  @property
  def head(self) -> Optional[str]: return self.data[0] if len(self.data) > 0 else None
  @property
  def tail(self) -> Optional[str]: return self.data[-1] if len(self.data) > 0 else None


  def endswith(self, ix) -> bool:
    slow = str(self).lower()
    if isinstance(ix, list):
      for element in ix:
        if slow.endswith(element.lower()): return True
      return False
    if '_' in ix: six = ix.replace('_',self.token)
    elif '/' in ix: six = ix.replace('/',self.token)
    else: six = ix.lower()
    return slow.endswith(six)
  def startswith(self, ix) -> bool:
    slow = str(self).lower()
    if isinstance(ix, list):
      for element in ix:
        if slow.startswith(element.lower()): return True
      return False
    if '_' in ix: six = ix.replace('_', self.token)
    elif '/' in ix: six = ix.replace('/', self.token)
    else: six = ix.lower()
    return slow.startswith(six)


  def extract(self, s:str, default=None):
    """
    Removes element by value and returns it or default
    ! modifies self.data
    """
    if s in self.data: return self.data.pop(self.data.index(s))
    return default


  def discard(self, element): self.data = [e for e in self.data if not e == element]
  def pophead(self) -> Optional[str]: return self.data.pop(0) if len(self.data) > 0 else None
  def poptail(self) -> Optional[str]: return self.data.pop(-1) if len(self.data) > 0 else None
  def popsuffix(self, ix):
    if self.endswith(ix):
      if '_' in ix and self.token != '_': ix = ix.replace('_',self.token)
      elif '/' in ix and self.token != '/': ix = ix.replace('/',self.token)
      self.data = self._any2list(str(self).replace(ix, ''))
      return self.token.join(self._any2list(ix))
  def popprefix(self, ix):
    if self.startswith(ix):
      if '_' in ix and self.token != '_': ix = ix.replace('_', self.token)
      elif '/' in ix and self.token != '/': ix = ix.replace('/', self.token)
      self.data = self._any2list(str(self).replace(ix, ''))
      return self.token.join(self._any2list(ix))
  def popxfix(self, ix): return self.popsuffix(ix) or self.popprefix(ix)


class y2path(y2list):
  def __init__(self, *args):
    data = []
    self.token = '/'

    for a in args: data += self._any2list(a)
    self.data = self._any2list(data)


class y2topic(y2path):
  def is_wildcard(self) -> bool: return bool(set(self.data) & {"#", "+"})


class y2slug(y2list):
  def __init__(self, o):
    self.token = '_'

    if '@' in str(o): o = str(o).split('@')[0]
    self.data = self._any2list(o)
# endregion
# region y2eid
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


# y2 types are _DC-annotatable; registered here so gppu.py never imports iot.
# _DC._DC_TYPE_MAP copied the base map at class definition, so patch both.
_DC_BASE_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic}
_DC._DC_TYPE_MAP |= {'y2eid': y2eid, 'y2topic': y2topic}


# region mqtt
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type MqttPayload = JsonValue | bytes
type MqttCallback = Callable[[y2topic, object], object | Awaitable[object]]


if aiomqtt is None:
  class _MqttError(Exception): pass
else:
  _MqttError = aiomqtt.MqttError


class mixin_Mqtt:
  """Reconnecting MQTT transport for a host with ``_spawn`` and logging."""

  _CLIENT_KEYS = ('hostname', 'port', 'username', 'password', 'identifier')
  MQTT_RECONNECT_DELAY = 5

  connection: dict[str, Any]
  MQTT_PROTOCOL: Any = None
  _client: Any = None
  _mqtt_task: Any = None
  _callbacks: dict[y2topic, list[tuple[MqttCallback, object]]]
  _subscriptions: dict[y2topic, int]
  _mqtt_lock: asyncio.Lock
  _callback_lock: asyncio.Lock

  def _start_mqtt(self):
    task = self._mqtt_task
    if task is not None and not task.done(): return task

    coroutine = self._mqtt_loop()
    try: task = self._spawn(coroutine)
    except BaseException:
      coroutine.close()
      raise
    self._mqtt_task = task
    return task

  def _ensure_mqtt_state(self) -> None:
    if getattr(self, '_mqtt_lock', None) is not None: return
    self._callbacks = {}
    self._subscriptions = {}
    self._mqtt_lock = asyncio.Lock()
    self._callback_lock = asyncio.Lock()

  async def mqtt_listen(self, callback: MqttCallback, topic: y2topic | str, payload: object = None, **data: Any) -> None:
    self._ensure_mqtt_state()
    topic = y2topic(topic)
    qos = int(data.get('qos', 0))

    async with self._mqtt_lock:
      callbacks = self._callbacks.setdefault(topic, [])
      entry = (callback, payload)
      if entry not in callbacks: callbacks.append(entry)

      old_qos = self._subscriptions.get(topic, -1)
      qos = max(old_qos, qos)
      self._subscriptions[topic] = qos
      client = self._client if qos != old_qos else None

    if client is not None: await client.subscribe(str(topic), qos=qos)

  async def mqtt_publish(self, topic: y2topic | str, payload: MqttPayload = '', **data: Any) -> None:
    client = self._client
    if client is None: return

    if isinstance(payload, (dict, list)): wire_payload = json.dumps(payload)
    elif isinstance(payload, bytes): wire_payload = payload
    else: wire_payload = str(payload)
    retain = bool(data.pop('retain', False))
    qos = int(data.pop('qos', 0))
    expiry = data.pop('expiry', None)
    properties = None

    if expiry is not None or data:
      properties = Properties(PacketTypes.PUBLISH)
      if expiry is not None: properties.MessageExpiryInterval = int(expiry)
      if data: properties.UserProperty = [(key, str(value)) for key, value in data.items()]

    await client.publish(str(topic), wire_payload, qos=qos, retain=retain, properties=properties)

  @property
  def _status_topic(self) -> y2topic:
    return y2topic(self.connection.get('status_topic', ''))

  def _mqtt_client(self):
    if aiomqtt is None: raise RuntimeError('aiomqtt is required for mixin_Mqtt')
    options = {key: self.connection[key] for key in self._CLIENT_KEYS if key in self.connection}
    if self.MQTT_PROTOCOL is not None: options['protocol'] = self.MQTT_PROTOCOL
    if self._status_topic: options['will'] = aiomqtt.Will(topic=str(self._status_topic), payload=b'offline', qos=1, retain=True)
    return aiomqtt.Client(**options)

  def _mqtt_tasks(self) -> Iterable[Coroutine[Any, Any, object]]: return ()

  async def _mqtt_loop(self) -> None:
    self._ensure_mqtt_state()
    while True:
      try:
        async with self._mqtt_client() as client:
          self._client = client
          try:
            self.Info('connected:', self.connection.get('hostname'), self.connection.get('port'))
            await self._mqtt_replay(client)
            if self._status_topic: await client.publish(str(self._status_topic), 'online', qos=1, retain=True)

            async with asyncio.TaskGroup() as tasks:
              dispatch = tasks.create_task(self._mqtt_dispatch(client))
              extras = [tasks.create_task(coroutine) for coroutine in self._mqtt_tasks()]
              await dispatch
              for task in extras: task.cancel()
          finally:
            self._client = None
            if self._status_topic:
              try: await client.publish(str(self._status_topic), 'offline', qos=1, retain=True)
              except _MqttError: pass
      except* _MqttError as errors:
        self.Warn(f'mqtt error, reconnect in {self.MQTT_RECONNECT_DELAY}s:', *errors.exceptions)
      finally:
        self._client = None

      await asyncio.sleep(self.MQTT_RECONNECT_DELAY)

  async def _mqtt_replay(self, client: Any) -> None:
    async with self._mqtt_lock: subscriptions = tuple(self._subscriptions.items())
    for topic, qos in subscriptions: await client.subscribe(str(topic), qos=qos)

  async def _mqtt_dispatch(self, client: Any) -> None:
    async for message in client.messages:
      topic = str(message.topic)
      raw = message.payload.decode(errors='replace') if isinstance(message.payload, bytes) else str(message.payload)
      payload: object = raw
      structured = raw.lstrip()
      if structured[:1] in '[{':
        try: payload = json.loads(structured)
        except json.JSONDecodeError: pass

      async with self._mqtt_lock:
        callbacks = [callback for pattern, entries in self._callbacks.items()
                     if self._topic_matches(topic, str(pattern))
                     for callback, expected in entries
                     if expected is None or expected == payload]

      for callback in callbacks: self._spawn(self._mqtt_callback(callback, y2topic(topic), payload))

  async def _mqtt_callback(self, callback: MqttCallback, topic: y2topic, payload: object) -> None:
    async with self._callback_lock:
      try:
        result = callback(topic, payload)
        if inspect.isawaitable(result): await result
      except Exception as error:
        self.Warn('callback error:', topic, error)

  @staticmethod
  def _topic_matches(topic: str, pattern: str) -> bool:
    if topic.startswith('$') and not pattern.startswith('$'): return False
    topic_parts = topic.split('/')
    pattern_parts = pattern.split('/')
    for index, expected in enumerate(pattern_parts):
      if expected == '#': return index == len(pattern_parts) - 1
      if index == len(topic_parts) or expected not in ('+', topic_parts[index]): return False
    return len(topic_parts) == len(pattern_parts)


class MqttApp(mixin_Mqtt, AsyncApp):
  """AsyncApp with one reconnecting MQTT client."""

  async def subscribe(self) -> None: pass

  async def start(self) -> None:
    await super().start()
    await self.subscribe()
    self._start_mqtt()
# endregion


# $$
# $$        Event-loop bridge and serialized controls
# $$
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

  def _get_loop(self) -> asyncio.AbstractEventLoop:
    raise NotImplementedError


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
    if aiohttp is None: raise RuntimeError('aiohttp is required for HTTPControl')
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

