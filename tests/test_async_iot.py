from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import unittest
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from gppu import AsyncApp, Env, EventLoopBridge, HTTPControl, JSONHTTPControl, SerializedControl, mixin_Mqtt
from gppu.iot import aiohttp


Env.data = {}
Env.initialized = True


class _FiniteApp(AsyncApp):
  values: list[int]
  connection: dict[str, Any]

  def setup(self) -> None:
    self.seen = list(self.values)

  async def start(self) -> None:
    self._spawn(self._worker())

  async def _worker(self) -> None:
    await asyncio.sleep(0)
    self.seen.append(3)


class _ExternalLoop(EventLoopBridge):
  def __init__(self, loop: asyncio.AbstractEventLoop): self.loop = loop
  def _get_loop(self) -> asyncio.AbstractEventLoop: return self.loop


class AsyncAppTests(unittest.IsolatedAsyncioTestCase):
  async def test_setup_run_and_dc_generics(self) -> None:
    app = _FiniteApp(name='finite', data={'values': [1, 2], 'connection': {'hostname': 'broker'}})
    self.assertEqual(app.seen, [1, 2])
    self.assertEqual(app.connection, {'hostname': 'broker'})
    await app.run()
    self.assertEqual(app.seen, [1, 2, 3])

  async def test_spawn_requires_active_run(self) -> None:
    app = _FiniteApp(name='finite', data={'values': []})
    coroutine = asyncio.sleep(0)
    with self.assertRaises(RuntimeError): app._spawn(coroutine)
    self.assertEqual(coroutine.cr_frame, None)


class EventLoopBridgeTests(unittest.IsolatedAsyncioTestCase):
  async def test_submit_call_and_reentrancy_guard(self) -> None:
    bridge = _ExternalLoop(asyncio.get_running_loop())

    async def add(left: int, right: int) -> int:
      await asyncio.sleep(0)
      return left + right

    task = bridge.submit(add, 2, 3)
    self.assertIsInstance(task, asyncio.Task)
    self.assertEqual(await task, 5)
    self.assertEqual(await asyncio.to_thread(bridge.call, add, 4, 5), 9)
    with self.assertRaisesRegex(RuntimeError, 'cannot block'): bridge.call(add, 1, 1)


class _Control(SerializedControl):
  def __init__(self, shared: dict[str, Any]):
    self.active = 0
    self.max_active = 0
    self.shared = shared

  def execute(self, value: int) -> tuple[int, int]:
    return self._control_call(self._execute, value)

  async def _execute(self, value: int) -> tuple[int, int]:
    self.active += 1
    self.max_active = max(self.max_active, self.active)
    with self.shared['lock']:
      self.shared['active'] += 1
      self.shared['max_active'] = max(self.shared['max_active'], self.shared['active'])
    try:
      await asyncio.sleep(0.01)
      return value, threading.get_ident()
    finally:
      with self.shared['lock']: self.shared['active'] -= 1
      self.active -= 1


class SerializedControlTests(unittest.TestCase):
  def test_per_instance_serialization_and_cross_instance_concurrency(self) -> None:
    shared = {'active': 0, 'max_active': 0, 'lock': threading.Lock()}
    left = _Control(shared)
    right = _Control(shared)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
      output = list(pool.map(lambda value: (left if value % 2 else right).execute(value), range(30)))

    self.assertEqual(sorted(value for value, _ in output), list(range(30)))
    self.assertEqual(left.max_active, 1)
    self.assertEqual(right.max_active, 1)
    self.assertEqual(shared['max_active'], 2)
    self.assertIsNot(left._control_lock, right._control_lock)
    self.assertEqual(len({thread_id for _, thread_id in output}), 1)


class _Handler(BaseHTTPRequestHandler):
  protocol_version = 'HTTP/1.0'

  def log_message(self, *_: Any) -> None: pass

  def _write(self, status: int, body: bytes, content_type: str = 'text/plain') -> None:
    self.send_response(status)
    self.send_header('Content-Type', content_type)
    self.send_header('Content-Length', str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def do_GET(self) -> None:
    if self.path == '/text': self._write(200, b'plain text')
    elif self.path == '/json': self._write(200, b'{"value": 7}', 'application/json')
    elif self.path == '/null': self._write(200, b'null', 'application/json')
    else: self._write(503, b'failed')

  def do_POST(self) -> None:
    size = int(self.headers.get('Content-Length', 0))
    body = self.rfile.read(size)
    if self.path == '/echo': self._write(200, body, self.headers.get('Content-Type', 'text/plain'))
    elif self.path == '/json':
      payload = json.loads(body)
      self._write(200, json.dumps({'received': payload}).encode(), 'application/json')
    else: self._write(404, b'not found')


class _TextControl(HTTPControl): pass
class _JsonControl(JSONHTTPControl): pass


@unittest.skipIf(aiohttp is None, 'aiohttp is not installed')
class HTTPControlTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    cls.server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
    cls.thread.start()
    cls.base_url = f'http://127.0.0.1:{cls.server.server_port}'

  @classmethod
  def tearDownClass(cls) -> None:
    cls.server.shutdown()
    cls.server.server_close()
    cls.thread.join()

  def test_text_transport(self) -> None:
    control = _TextControl()
    self.assertEqual(control._http_get(f'{self.base_url}/text'), 'plain text')
    self.assertEqual(
      control._http_post(f'{self.base_url}/echo', 'payload', headers={'Content-Type': 'text/custom'}),
      'payload',
    )
    self.assertIsNone(control._http_get(f'{self.base_url}/error'))

  def test_explicit_json_layer(self) -> None:
    control = _JsonControl()
    self.assertEqual(control._json_get(f'{self.base_url}/json'), {'value': 7})
    self.assertEqual(control._json_post(f'{self.base_url}/json', {'x': 1}), {'received': {'x': 1}})
    self.assertIsNone(control._json_get(f'{self.base_url}/null'))


class _FakeClient:
  def __init__(self, messages=()):
    self.messages = messages
    self.subscriptions: list[tuple[str, int]] = []
    self.published: list[tuple[str, Any, dict[str, Any]]] = []

  async def subscribe(self, topic: str, qos: int = 0) -> None:
    self.subscriptions.append((topic, qos))

  async def publish(self, topic: str, payload: Any, **data: Any) -> None:
    self.published.append((topic, payload, data))


class _Message:
  def __init__(self, topic: str, payload: str | bytes):
    self.topic = topic
    self.payload = payload


class _Messages:
  def __init__(self, messages: list[_Message]): self.messages = messages
  def __aiter__(self): return self._iterate()

  async def _iterate(self):
    for message in self.messages: yield message


class _MqttHost(mixin_Mqtt):
  def __init__(self):
    self.connection = {}
    self.tasks: set[asyncio.Task[Any]] = set()
    self.warnings: list[tuple[Any, ...]] = []

  def _spawn(self, coroutine):
    task = asyncio.create_task(coroutine)
    self.tasks.add(task)
    task.add_done_callback(self.tasks.discard)
    return task

  def Info(self, *args: Any) -> None: pass
  def Warn(self, *args: Any) -> None: self.warnings.append(args)


class _ReconnectHost(_MqttHost):
  MQTT_RECONNECT_DELAY = 0

  def __init__(self):
    super().__init__()
    self.connections = 0
    self.extra_started = 0
    self.extra_stopped = 0

  @asynccontextmanager
  async def _mqtt_client(self):
    self.connections += 1
    yield _FakeClient(_Messages([]))

  def _mqtt_tasks(self): return [self._extra()]

  async def _extra(self):
    self.extra_started += 1
    try: await asyncio.Event().wait()
    finally: self.extra_stopped += 1


class MqttMixinTests(unittest.IsolatedAsyncioTestCase):
  async def test_registration_qos_publish_dispatch_and_wildcards(self) -> None:
    host = _MqttHost()
    host._ensure_mqtt_state()
    client = _FakeClient()
    host._client = client
    seen: list[tuple[str, Any]] = []

    async def callback(topic, payload): seen.append((str(topic), payload))

    await host.mqtt_listen(callback, 'a/+/c', qos=0)
    await host.mqtt_listen(callback, 'a/+/c', qos=1)
    await host.mqtt_listen(callback, 'a/+/c', qos=0)
    self.assertEqual(client.subscriptions, [('a/+/c', 0), ('a/+/c', 1)])

    await host.mqtt_publish('out', {'x': 1}, retain=True, qos=1)
    self.assertEqual(client.published[-1], ('out', '{"x": 1}', {'qos': 1, 'retain': True, 'properties': None}))

    client.messages = _Messages([
      _Message('a/b/c', b'  {"value": 2}'),
      _Message('a/b/d', b'ignored'),
    ])
    await host._mqtt_dispatch(client)
    if host.tasks: await asyncio.gather(*host.tasks)
    self.assertEqual(seen, [('a/b/c', {'value': 2})])

    matches = host._topic_matches
    self.assertTrue(matches('a', 'a/#'))
    self.assertTrue(matches('a/b/c', 'a/+/c'))
    self.assertFalse(matches('a/b/c', 'a/+/d'))
    self.assertFalse(matches('a/b', 'a/#/b'))
    self.assertFalse(matches('$SYS/broker', '#'))
    self.assertTrue(matches('$SYS/broker', '$SYS/#'))

  async def test_connection_tasks_are_recreated_and_cleaned_up(self) -> None:
    host = _ReconnectHost()
    task = asyncio.create_task(host._mqtt_loop())
    try:
      while host.connections < 3: await asyncio.sleep(0)
    finally:
      task.cancel()
      with self.assertRaises(asyncio.CancelledError): await task

    self.assertGreaterEqual(host.extra_started, 2)
    self.assertEqual(host.extra_stopped, host.extra_started)


if __name__ == '__main__':
  unittest.main()
