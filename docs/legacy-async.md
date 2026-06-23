# Old version of async plumbing, retained for reference. 

```python
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
class _AsyncLoopThread(_mixin):
  def call[T, **P](self, function: Callable[P, Coroutine[Any, Any, T]], /, *args: P.args, **kwargs: P.kwargs) -> T:
    return asyncio.run_coroutine_threadsafe(function(*args, **kwargs), self._get_loop()).result()


class _HTTPControl(_ControlBase):
  _http_lock: asyncio.Lock | None = None

  def _http_request(self, method: str, url: str, payload: JsonObject | None = None) -> JsonObject | None:
    return _AsyncLoopThread.from_child(self).call(self._http_request_async, method, url, payload)

  async def _http_request_async(self, method: str, url: str, payload: JsonObject | None = None) -> JsonObject | None:
    lock = self._http_lock
    if lock is None: lock = self._http_lock = asyncio.Lock()

    async with lock:
      try:
        timeout = aiohttp.ClientTimeout(total=self._http_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
          async with session.request(method, url, json=payload, headers=self._http_headers, ssl=self._http_ssl) as response:
            return json.loads(await response.text())
      except (aiohttp.ClientError, TimeoutError, OSError, json.JSONDecodeError):
        return None


class _CoroutineRunner(_mixin):
  def run(self, awaitable: Awaitable[_T]) -> _T:
    return asyncio.run_coroutine_threadsafe(awaitable, self._ensure_event_loop()).result()

class _CoroutineRunner(_mixin):
  _loop_start_lock = threading.Lock()


  @staticmethod
  def _run_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


  def _ensure_event_loop(self) -> asyncio.AbstractEventLoop:
    loop = getattr(self, '_coroutine_loop', None)
    if loop is not None: return loop

    with self._loop_start_lock:
      loop = getattr(self, '_coroutine_loop', None)
      if loop is None:
        loop = asyncio.new_event_loop()
        self._coroutine_loop = loop
        threading.Thread(target=self._run_event_loop, args=(loop,), daemon=True, name=f'async-{getattr(self, "name", type(self).__name__)}').start()

    return loop

  def run(self, coroutine: Coroutine[Any, Any, _T]) -> _T:
    return asyncio.run_coroutine_threadsafe(
      coroutine,
      self._ensure_event_loop(),
    ).result()


class _HTTPControl(_mixin):
  _control_address: str

  _http_headers: dict[str, str] | None = None
  _http_ssl: ssl.SSLContext | None = None
  _http_timeout: int = 10

  def __init__(self, *args, **kwargs):
    self._http_lock = threading.Lock()


  def _http_request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with self._http_lock:
      return self._coroutine_runner.run(self._send_http(method, url, payload))


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
        async with session.request(method, url, json=payload, headers=self._http_headers or None, ssl=self._http_ssl) as resp:
          return json.loads(await resp.text())
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, json.JSONDecodeError): return None


class _SerialControl(_mixin):
  command_suffix: str = "\n\r"

  def _send_serial(self, command: str, **data) -> None: return _io_host(self).io_run(self._control_address, self._send_serial_async(command, **data))
  
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
# class _IORuntime(_mixin):
#   """Owns a long-lived asyncio event loop on a daemon thread plus a per-key
#   threading.Lock rate gate. `io_run(key, coro)` submits the coroutine and
#   blocks the calling thread for its result, serialized per `key`. Independent
#   of AppDaemon's event loop — mix into StateManager (or any other host).
#   Lazy: no __init needed, allocates loop/gates dict on first use."""

#   _io_start_lock = threading.Lock()

#   def _io_get_loop(self) -> asyncio.AbstractEventLoop:
#     loop = getattr(self, '_io_loop', None)
#     if loop is not None: return loop
#     with _IORuntime._io_start_lock:
#       loop = getattr(self, '_io_loop', None)
#       if loop is None:
#         loop = asyncio.new_event_loop()
#         name = f"io-{getattr(self, 'name', type(self).__name__)}"
#         threading.Thread(target=loop.run_forever, daemon=True, name=name).start()
#         self._io_loop = loop
#     return loop

#   def _io_get_gate(self, key: str) -> threading.Lock:
#     gates = getattr(self, '_io_gates', None)
#     if gates is None: gates = self._io_gates = {}
#     gate = gates.get(key)
#     if gate is None: gate = gates[key] = threading.Lock()
#     return gate

#   def io_run(self, key: str, coro):
#     with self._io_get_gate(key):
#       return asyncio.run_coroutine_threadsafe(coro, self._io_get_loop()).result()


# def _io_host(obj):
#   """Walk parent chain to find the first mixin_IORuntime ancestor."""
#   cur = obj
#   while cur is not None:
#     if isinstance(cur, _IORuntime): return cur
#     cur = getattr(cur, 'parent', None)
#   raise RuntimeError(f"{obj!r} has no mixin_IORuntime ancestor")


```