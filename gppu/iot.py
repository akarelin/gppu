"""IoT primitives: y2list/y2path/y2topic/y2slug/y2eid types, the shared
mqtt capability mixin (mixin_Mqtt, on gppu.app.AsyncApp) used by the any2mqtt
suite, and device control mixins (HTTP, Serial, Serial-over-HTTP).
Third-party IO deps are optional — install gppu[iot] (aiomqtt + aiohttp +
telnetlib3) or just gppu[mqtt] (aiomqtt) for the pieces you use."""
from __future__ import annotations

import asyncio
import json
import re
import threading
from collections import UserList
from typing import Any, Callable, ClassVar, List, Optional
from urllib.parse import urlparse

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
try:
  import telnetlib3
except ImportError:
  telnetlib3 = None  # type: ignore[assignment]

from .gppu import _DC, _DC_BASE_TYPE_MAP, Error, _mixin, mixin_Logger
from .app import protocol_Async


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
""" Shared mqtt plumbing for the any2mqtt transform services (brul2mqtt,
motion2mqtt, ...). The library is not a service: each service owns its broker
login, identifier, and status/<service> LWT. mixin_Mqtt is a capability mixin on
AsyncApp — its reconnecting client runs as a spawned task; the app sets
self.connection (its config block) in __init, and subscribe/publish are the only
public surface."""
_MQTT_KW = ('hostname', 'port', 'username', 'password', 'identifier')


class mixin_Mqtt(protocol_Async, mixin_Logger):
  connection: dict                  # broker config block; set by the app's __init
  MQTT_PROTOCOL = None              # aiomqtt.ProtocolVersion.V5 to opt in (message-expiry)

  def __init(self):
    self._callbacks: dict = {}      # topic pattern -> [(cb, payload_filter)]
    self._subs: set = set()         # active subscriptions
    self._client = None
    self._lock = asyncio.Lock()
    self._cb_lock = asyncio.Lock()

  def __start(self):
    self._spawn(self._mqtt_loop())

  # ---- public API (y2api-aligned) ----
  async def mqtt_listen(self, cb: Callable, topic: y2topic | str, payload=None, **data):
    """Register cb(topic, payload) for a topic pattern and subscribe. cb may be
    sync or async; `payload`, if given, is an exact-match filter (fire only on
    that payload). Safe before connect — the reconnect loop replays the
    subscription. `**data` may carry a `qos` for the subscription."""
    topic = y2topic(topic)
    entry = (cb, payload)
    async with self._lock:
      cbs = self._callbacks.setdefault(topic, [])
      if entry not in cbs: cbs.append(entry)
      if topic not in self._subs:
        self._subs.add(topic)
        if self._client is not None:
          await self._client.subscribe(str(topic), qos=int(data.get('qos', 0)))

  async def mqtt_publish(self, topic: y2topic | str, payload: str | dict | float = "", **data):
    """Publish. dict/list payloads are JSON-encoded. `**data`: `retain`, `qos`,
    `expiry` (MQTT5 message-expiry, seconds); any remaining keys become MQTT5
    UserProperty pairs. Dropped silently while reconnecting (no client)."""
    if self._client is None: return
    payload = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
    retain = bool(data.pop('retain', False))
    qos = int(data.pop('qos', 0))
    expiry = data.pop('expiry', None)
    props = None
    if expiry is not None or data:
      props = Properties(PacketTypes.PUBLISH)
      if expiry is not None: props.MessageExpiryInterval = int(expiry)
      if data: props.UserProperty = [(k, str(v)) for k, v in data.items()]
    await self._client.publish(str(topic), payload, qos=qos, retain=retain, properties=props)

  # ---- internal ----
  @property
  def _status_topic(self) -> y2topic:
    return y2topic(self.connection.get('status_topic', ''))

  def _mqtt_client(self):
    kw = {k: self.connection[k] for k in _MQTT_KW if k in self.connection}
    if self.MQTT_PROTOCOL is not None: kw['protocol'] = self.MQTT_PROTOCOL
    if self._status_topic:
      kw['will'] = aiomqtt.Will(topic=str(self._status_topic), payload=b'offline', qos=1, retain=True)
    return aiomqtt.Client(**kw)

  def _mqtt_tasks(self, client) -> list:
    return []                       # override: poll loops, control-channel routers

  async def _mqtt_loop(self):
    while True:
      try:
        async with self._mqtt_client() as client:
          self._client = client
          self.Info('connected:', self.connection.get('hostname'), self.connection.get('port'))
          await self._mqtt_replay(client)
          if self._status_topic:
            await client.publish(str(self._status_topic), 'online', qos=1, retain=True)
          async with asyncio.TaskGroup() as tg:
            tg.create_task(self._mqtt_dispatch(client))
            for extra in self._mqtt_tasks(client): tg.create_task(extra)
      except aiomqtt.MqttError as e:
        self.Warn('mqtt error, reconnect in 5s:', e)
        await asyncio.sleep(5)
      finally:
        self._client = None

  async def _mqtt_replay(self, client):
    async with self._lock: subs = list(self._subs)
    for topic in subs: await client.subscribe(str(topic), qos=0)

  async def _mqtt_dispatch(self, client):
    async for msg in client.messages:
      topic = str(msg.topic)
      raw = msg.payload.decode() if isinstance(msg.payload, bytes) else str(msg.payload)
      if raw and raw[0] == '{':
        try: payload = json.loads(raw)
        except json.JSONDecodeError: payload = raw
      else:
        payload = raw
      async with self._lock:
        fire = [cb for pattern, cbs in self._callbacks.items()
                if self._topic_matches(topic, str(pattern))
                for (cb, filt) in cbs if filt is None or filt == payload]
      for cb in fire:
        self._spawn(self._safe_cb(cb, y2topic(topic), payload))

  async def _safe_cb(self, cb, topic, payload):
    async with self._cb_lock:
      try:
        result = cb(topic, payload)
        if asyncio.iscoroutine(result): await result
      except Exception as e:
        self.Warn('callback error:', topic, e)

  @staticmethod
  def _topic_matches(topic: str, pattern: str) -> bool:
    if pattern.endswith('/#'):
      return topic.startswith(pattern[:-2])
    return topic == pattern
# endregion


# $$                                                              
# $$        Control mixins (HTTP, Serial, Serial-over-HTTP)       
# $$                                                              
class _ControlBase:
  _control_address: str
  _http_timeout: int = 10


class _IORuntime(_mixin):
  """Owns a long-lived asyncio event loop on a daemon thread plus a per-key
  threading.Lock rate gate. `io_run(key, coro)` submits the coroutine and
  blocks the calling thread for its result, serialized per `key`. Independent
  of AppDaemon's event loop — mix into StateManager (or any other host).
  Lazy: no __init needed, allocates loop/gates dict on first use."""

  _io_start_lock = threading.Lock()

  def _io_get_loop(self) -> asyncio.AbstractEventLoop:
    loop = getattr(self, '_io_loop', None)
    if loop is not None: return loop
    with _IORuntime._io_start_lock:
      loop = getattr(self, '_io_loop', None)
      if loop is None:
        loop = asyncio.new_event_loop()
        name = f"io-{getattr(self, 'name', type(self).__name__)}"
        threading.Thread(target=loop.run_forever, daemon=True, name=name).start()
        self._io_loop = loop
    return loop

  def _io_get_gate(self, key: str) -> threading.Lock:
    gates = getattr(self, '_io_gates', None)
    if gates is None: gates = self._io_gates = {}
    gate = gates.get(key)
    if gate is None: gate = gates[key] = threading.Lock()
    return gate

  def io_run(self, key: str, coro):
    with self._io_get_gate(key):
      return asyncio.run_coroutine_threadsafe(coro, self._io_get_loop()).result()


def _io_host(obj):
  """Walk parent chain to find the first mixin_IORuntime ancestor."""
  cur = obj
  while cur is not None:
    if isinstance(cur, _IORuntime): return cur
    cur = getattr(cur, 'parent', None)
  raise RuntimeError(f"{obj!r} has no mixin_IORuntime ancestor")


class _HTTPControl(_ControlBase, _IORuntime):
  _http_headers: dict[str, str] | None = None   # extra headers merged into every request (e.g. auth keys)
  _http_ssl = None                              # ssl.SSLContext for https; None = urllib default (verified)

  def _http_get(self, url: str) -> dict | None:
    return _io_host(self).io_run(urlparse(url).hostname or url, self._http_request_async('GET', url))

  def _http_put(self, url: str, payload: dict) -> dict | None:
    return _io_host(self).io_run(urlparse(url).hostname or url, self._http_request_async('PUT', url, payload))

  def _http_post(self, url: str, payload: dict) -> dict | None:
    return _io_host(self).io_run(urlparse(url).hostname or url, self._http_request_async('POST', url, payload))

  async def _http_request_async(self, method: str, url: str, payload: dict | None = None) -> dict | None:
    # Genuine async IO (aiohttp) — was a blocking urllib.urlopen inside this async def,
    # which stalled the StateManager IO loop while it queued the next resource call.
    try:
      timeout = aiohttp.ClientTimeout(total=self._http_timeout)
      async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, json=payload,
                                   headers=self._http_headers or None, ssl=self._http_ssl) as resp:
          return json.loads(await resp.text())
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, json.JSONDecodeError): return None


class _SerialControl(_mixin):
  command_suffix: str = "\n\r"

  def _send_serial(self, command: str, **data) -> None:
    return _io_host(self).io_run(self._control_address, self._send_serial_async(command, **data))
  async def _send_serial_async(self, command: str, **data) -> None:
    writer = None
    try:
      reader, writer = await telnetlib3.open_connection(host=self._control_address, port=23)
      assert reader is not None and writer is not None, "Failed to establish telnet connection"
      writer.write(command + self.command_suffix)
      await writer.drain()
    except Exception as e: Error("Error in telnet command", "INFO", command, "DIM", ":", "BRIGHT", e); raise
    finally:
      if writer: writer.close()


class _SerialHTTPControl(_SerialControl, _HTTPControl):
  def _send_serial(self, command: str, **data) -> None:
    url = f"http://{self._control_address}/api/host/modules/1/ports/1/data"
    self._http_post(url, payload={'data': command + "\n"})