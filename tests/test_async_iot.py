from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
import threading
import unittest
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from gppu import AsyncApp, mixin_EventLoopBridge, HTTPControl, JSONHTTPControl, SerializedControl
from gppu.iot import aiohttp
from gppu.tui import TUIApp


class _FiniteApp(AsyncApp):
  def __init(self) -> None:
    self.seen = list(self.my('values'))

  def __start(self) -> None:
    self._spawn(self._worker())

  async def _worker(self) -> None:
    await asyncio.sleep(0)
    self.seen.append(3)


class _ExternalLoop(mixin_EventLoopBridge):
  def __init__(self, loop: asyncio.AbstractEventLoop): self.loop = loop
  def _get_loop(self) -> asyncio.AbstractEventLoop: return self.loop


class AsyncAppTests(unittest.IsolatedAsyncioTestCase):
  async def test_init_on_construction_then_load_and_start_in_run(self) -> None:
    app = _FiniteApp(config={'values': [1, 2]})
    self.assertEqual(app.seen, [1, 2])
    await app.run()
    self.assertEqual(app.seen, [1, 2, 3])

  async def test_spawn_requires_active_run(self) -> None:
    app = _FiniteApp(config={'values': []})
    coroutine = asyncio.sleep(0)
    with self.assertRaises(RuntimeError): app._spawn(coroutine)
    self.assertEqual(coroutine.cr_frame, None)


class _Grid(TUIApp):
  def __start(self) -> None: self.steps = ['start']


class RunParallelTests(unittest.IsolatedAsyncioTestCase):
  async def test_launch_hands_each_line_and_reports_the_exit(self) -> None:
    app, lines = AsyncApp(name='parallel'), []
    self.assertIsNone(await app.launch([sys.executable, '-c', "print('one'); print('two')"], lines.append, '.', dict(os.environ)))
    self.assertEqual(lines, ['one', 'two'])
    self.assertEqual(await app.launch([sys.executable, '-c', 'raise SystemExit(3)'], lines.append, '.', dict(os.environ)),
                     'process exited with 3')

  async def test_run_parallel_starts_every_unit_and_holds_back_a_clash(self) -> None:
    app, started, ended, failures = AsyncApp(name='parallel'), [], [], []

    async def run(unit: str) -> None:
      started.append(unit)
      if unit == 'b': raise ValueError(unit)
      for _ in range(3): await asyncio.sleep(0)
      ended.append(unit)

    await app.run_parallel(['a', 'b', 'c'], run, lambda unit, running: unit == 'c' and 'a' in running,
                           lambda unit, error: failures.append((unit, str(error))))
    self.assertEqual(started, ['a', 'b', 'c'])
    self.assertEqual(ended, ['a', 'c'])
    self.assertEqual(failures, [('b', 'b')])

  async def test_a_tui_app_is_an_async_app_and_launches_on_itself(self) -> None:
    app, lines = _Grid(), []
    self.assertIsInstance(app, AsyncApp)
    self.assertEqual(app.name, '_grid')
    async with app.run_test():
      self.assertIsNotNone(app._task_group)
      self.assertEqual(app.steps, ['start'])
      self.assertIsNone(await app.launch([sys.executable, '-c', "print('one')"], lines.append, '.', dict(os.environ)))
    self.assertEqual(lines, ['one'])
    self.assertIsNone(app._task_group)


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


if __name__ == '__main__':
  unittest.main()
