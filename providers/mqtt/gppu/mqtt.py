"""gppu.mqtt — provider: an MQTT broker through aiomqtt.

Replaces mixin_Mqtt, MqttApp, _MqttConfig and Env.from_mqtt: an app asks for a broker and runs its connection in
its own TaskGroup.

    connections:
      mqtt-i2: {provider: gppu.mqtt.Mqtt, hostname: i2, port: 1883}

    class Brultech(AsyncApp):
      async def main(self, mqtt: Mqtt = 'mqtt-i2'):
        await mqtt.listen(self.on_reading, 'brultech/+/raw')
        self._spawn(mqtt.serve())

The row holds the broker. What belongs to one process is written into ``mqtt.connection`` before ``serve``:
``identifier`` (a service and a command line on one host must not share one, or the broker drops the older), and
``status_topic`` for a service that announces itself with a retained online/offline and a last will.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from fnmatch import fnmatchcase
from collections.abc import Awaitable, Callable
from typing import Any

import aiomqtt
import yaml
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from gppu import AsyncApp, Env, Info, Provider, Warn, y2topic

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
          await self._dispatch(client)
        finally:
          self.connected.clear()
          self._client = None
          if status:
            try: await client.publish(status, 'offline', qos=1, retain=True)   # a clean DISCONNECT does not fire the will
            except aiomqtt.MqttError: pass
    except aiomqtt.MqttError as error:
      Warn(f'mqtt error, reconnect in {self.RECONNECT_DELAY}s:', error)

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
  offline if the process dies). ``{host}`` in a row's text is the app's host, so one row serves every host. ``wait``
  bounds, in seconds, how long ``main`` waits to be connected and configured; without it, ``main`` waits until it is.
  ``main`` prepares what the app needs and spawns lasting work, and may await ``self.serving`` to last as long as the
  connection; when it returns, ``on_message`` is subscribed to the row's ``listen`` topics. The connection is kept,
  reconnecting, until the app stops. An app that only reacts to its configured topics writes ``on_message`` and
  nothing else.

      recorder:
        connection: {hostname: mqtt, port: 1883, identifier: recorder, status_topic: status/recorder, listen: ['#']}
      panel:
        connection: {hostname: mqtt, status_topic: status/panel/{host}, wait: 5, config: {panel/config/scenes: panel/scenes}}

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
    row = {key: value.replace('{host}', self.host) if isinstance(value, str) else value for key, value in self.my('connection').items()}
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
