"""IoT primitives: y2list/y2path/y2topic/y2slug/y2eid types and the shared
mqtt service plumbing (MqttConnstring, MqttMixin, Transformer) used by the
any2mqtt suite. aiomqtt is optional — install gppu[mqtt] for the Mqtt* classes."""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import UserList
from typing import Any, Callable, ClassVar, List, Optional

try:
  import aiomqtt
except ImportError:
  aiomqtt = None  # type: ignore[assignment]

from .gppu import _DC, _DC_BASE_TYPE_MAP, App, mixin_Logger, safe_float
from .ymro import mixin_Stepper


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
# xx
# xx mqtt_connstring, MqttMixin, Transformer
# xx
""" Shared mqtt library plumbing for the any2mqtt transform services
(brul2mqtt, motion2mqtt, ...). The library is not a service: each service owns
its broker login, identifier, and status/<service> LWT."""
MQTT_CONN_FIELDS = {'hostname', 'port', 'username', 'password', 'identifier'}


def mqtt_connstring(conn: dict) -> dict:
  """aiomqtt.Client kwargs from a yaml connection: block — extra keys dropped."""
  return {k: v for k, v in conn.items() if k in MQTT_CONN_FIELDS}


class MqttMixin(mixin_Logger):
  connstring: dict

  def _mqtt_init(self):
    self._callbacks = {}
    self._client = None
    self._active_subscriptions = set()
    self._mqtt_lock = asyncio.Lock()
    self._cb_lock = asyncio.Lock()

  async def add_topic_listener(self, cb: Callable, topic: y2topic):
    async with self._mqtt_lock:
      cbs = self._callbacks.setdefault(topic, [])
      if cb not in cbs:
        cbs.append(cb)
      if topic not in self._active_subscriptions:
        self._active_subscriptions.add(topic)
        if self._client is not None:
          await self._client.subscribe(topic, qos=0)

  async def remove_topic_listener(self, cb: Callable, topic: y2topic):
    async with self._mqtt_lock:
      cbs = self._callbacks.get(topic)
      if not cbs:
        return
      try:
        cbs.remove(cb)
      except ValueError:
        return
      if cbs:
        return
      del self._callbacks[topic]
      self._active_subscriptions.discard(topic)
      if self._client is not None:
        await self._client.unsubscribe(topic)

  async def clear_listeners(self, topic: y2topic):
    async with self._mqtt_lock:
      self._callbacks.pop(topic, None)
      if topic in self._active_subscriptions:
        self._active_subscriptions.remove(topic)
        if self._client is not None:
          await self._client.unsubscribe(topic)

  async def mqtt_publish(self, topic: y2topic, payload: str | dict | int | float | None = None, retain: bool = False, **kw):
    if payload:
      if isinstance(payload, dict):
        payload = json.dumps(payload)
      else:
        payload = str(payload)
    await self._client.publish(str(topic), str(payload), **kw)

  def _mqtt_client(self):
    return aiomqtt.Client(**self.connstring)

  async def _mqtt_on_connect(self, client):
    self._client = client
    self.Info('connected:', self.connstring.get('hostname'), self.connstring.get('port'))
    async with self._mqtt_lock:
      topics = list(self._active_subscriptions)
    for topic in topics:
      await client.subscribe(topic, qos=0)

  async def _mqtt_dispatch(self, client):
    async for msg in client.messages:
      topic = str(msg.topic)
      raw = msg.payload.decode() if isinstance(msg.payload, bytes) else str(msg.payload)
      if raw and raw[0] == '{':
        try:
          payload = json.loads(raw)
        except json.JSONDecodeError:
          payload = raw
      else:
        payload = raw
      async with self._mqtt_lock:
        matches = [
          cb
          for pattern, cbs in self._callbacks.items()
          if self._topic_matches(topic, pattern)
          for cb in cbs
        ]
      for cb in matches:
        asyncio.create_task(self._safe_cb(cb, y2topic(topic), payload))

  async def _safe_cb(self, cb, topic, payload):
    async with self._cb_lock:
      try:
        await cb(topic, payload)
      except Exception as e:
        self.Warn('callback error:', topic, e)

  async def _mqtt_run(self):
    while True:
      try:
        async with self._mqtt_client() as client:
          await self._mqtt_on_connect(client)
          await self._mqtt_dispatch(client)
      except aiomqtt.MqttError as e:
        self.Warn('mqtt error, reconnect in 5s:', e)
        await asyncio.sleep(5)
      finally:
        self._client = None

  @staticmethod
  def _topic_matches(topic: str, pattern: str) -> bool:
    if pattern.endswith('/#'):
      return topic.startswith(pattern[:-2])
    return topic == pattern


class Transformer(App, MqttMixin, mixin_Stepper):
  NODATA_TIMEOUT = 60
  DEBOUNCE = 10

  def __init(self):
    conn = self.data.get('connection', {})
    self.connstring = mqtt_connstring(conn)
    self.status_topic = y2topic(conn.get('status_topic', ''))
    self.rules = self.data.get('rules', [])
    self._vals = {}
    self._last_pub = {}
    self._last_message_time = 0.0
    self._status = 'offline'
    self._mqtt_init()

  def __load(self): pass

  def __start(self):
    for pat in self.data.get('connection', {}).get('listen', []):
      self._callbacks.setdefault(pat, []).append(self._on_message)
      self._active_subscriptions.add(pat)
    asyncio.run(self._run())

  async def _run(self):
    will = aiomqtt.Will(
      topic=str(self.status_topic), payload=b'offline', qos=1, retain=True
    ) if self.status_topic else None
    while True:
      try:
        async with aiomqtt.Client(**self.connstring, will=will) as client:
          await self._mqtt_on_connect(client)
          if self.status_topic:
            await client.publish(str(self.status_topic), 'online', qos=1, retain=True)
          self._last_message_time = time.monotonic()
          self._status = 'online'
          watchdog = asyncio.create_task(self._watchdog())
          try:
            await self._mqtt_dispatch(client)
          finally:
            watchdog.cancel()
      except aiomqtt.MqttError as e:
        self.Warn('mqtt error, reconnect in 5s:', e)
        await asyncio.sleep(5)
      finally:
        self._client = None

  async def _watchdog(self):
    while self._client is not None:
      await asyncio.sleep(10)
      if self._status == 'online' and time.monotonic() - self._last_message_time > self.NODATA_TIMEOUT:
        self._status = 'no-data'
        self.Warn('no data for', self.NODATA_TIMEOUT, 's')
        if self.status_topic:
          await self.mqtt_publish(self.status_topic, 'no-data', qos=1, retain=True)

  async def _on_message(self, topic, payload):
    self._last_message_time = time.monotonic()
    if self._status == 'no-data':
      self._status = 'online'
      self.Info('data resumed')
      if self.status_topic:
        await self.mqtt_publish(self.status_topic, 'online', qos=1, retain=True)
    raw = payload.get('value') if isinstance(payload, dict) else payload
    if isinstance(raw, (int, float)):
      value = float(raw)
    else:
      value = safe_float(raw)
      if value is None: return
    self._vals[topic] = value
    now = time.monotonic()
    for rule in self.rules:
      for dest, val in self._cascade(rule, self._vals).items():
        self._vals[dest] = round(val, 1)
        if now - self._last_pub.get(dest, 0) >= self.DEBOUNCE:
          self._last_pub[dest] = now
          await self.mqtt_publish(dest, self._vals[dest], qos=0)


  @staticmethod
  def _cascade(rule, vals):
    src_prefix = rule['source_prefix']
    flip = 'sign_flip' in rule.get('processors', [])
    out = {}
    for name, inputs in rule['map'].items():
      groups = inputs if isinstance(inputs[0], list) else [inputs]
      totals, ok = [], True
      for group in groups:
        vs = []
        for r in group:
          v = vals.get(y2topic(r) if '/' in r else y2topic(src_prefix, r))
          if v is None:
            ok = False
            break
          vs.append(-v if flip else v)
        if not ok: break
        totals.append(sum(vs))
      if not ok: continue
      out[y2topic(rule['dest_prefix'], name)] = totals[0] - sum(totals[1:])
    return out
# endregion
