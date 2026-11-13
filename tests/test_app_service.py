"""AppService: configuration replaced from MQTT, the same as loading it again."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gppu import AppService, Env, mixin_Mqtt
from gppu import glob, glob_dict


@pytest.fixture(autouse=True)
def environment():
  previous, initialized = Env._my, Env.initialized
  Env.reset()
  yield
  Env.reset()
  Env._my, Env.initialized = previous, initialized


def test_subtree_replacement_preserves_other_config():
  Env.from_dict({'dc': {'scene': 'pc', 'stale': True}, 'ov': {'url': 'https://ov'}})
  Env.update_config({'scene': 'laptop'}, 'dc')
  assert glob_dict('dc') == {'scene': 'laptop'}
  assert glob('ov/url') == 'https://ov'


def test_invalid_config_does_not_replace_current_values():
  Env.from_dict({'dc': {'scene': 'pc'}})
  with pytest.raises(TypeError, match='mapping'): Env.update_config(['bad'])
  assert glob_dict('dc') == {'scene': 'pc'}


def test_removing_configured_trace_rules_clears_them():
  from gppu import TRACE_RULES
  previous = dict(TRACE_RULES)
  try:
    Env.from_dict({'trace_rules': {'all': True}})
    Env.update_config({})
    assert TRACE_RULES == {}
  finally:
    TRACE_RULES.clear()
    TRACE_RULES.update(previous)


class Messages:
  def __init__(self): self.queue = asyncio.Queue()
  def __aiter__(self): return self
  async def __anext__(self): return await self.queue.get()


class Client:
  def __init__(self, retained):
    self.retained = retained
    self.messages = Messages()
    self.subscriptions = []
    self.closed = False
    self.connected = asyncio.Event()
    self.connections = 0

  async def subscribe(self, topic, qos):
    self.subscriptions.append((topic, qos))
    if topic in self.retained: self.send(topic, self.retained[topic])

  def send(self, topic, payload):
    self.messages.queue.put_nowait(SimpleNamespace(topic=topic, payload=payload))


def mqtt_source(monkeypatch, retained, topics):
  client = Client(retained)

  @asynccontextmanager
  async def connect(self):
    client.connections += 1
    client.connected.set()
    try: yield client
    finally: client.closed = True

  monkeypatch.setattr(mixin_Mqtt, '_mqtt_client', connect)
  Env.from_dict({'local': {'keep': True}, 'consumer': {'config_mqtt': {'topics': topics}}})
  return client, {'connection': {'hostname': 'test-broker'}, 'topics': topics}


def test_mqtt_startup_loads_all_declared_topics_and_disconnects(monkeypatch):
  async def run():
    client, source = mqtt_source(monkeypatch,
      {'config/dc': b'scene: pc\n', 'config/ov': b'{"url":"https://ov"}'},
      {'config/dc': 'dc', 'config/ov': 'ov'})
    async with asyncio.timeout(2): await AppService.from_mqtt(source)
    assert glob_dict('') == {'local': {'keep': True}, 'consumer': {'config_mqtt': {'topics': source['topics']}}, 'dc': {'scene': 'pc'}, 'ov': {'url': 'https://ov'}}
    assert client.subscriptions == [('config/dc', 1), ('config/ov', 1)]
    assert client.closed
    assert client.connections == 1
  asyncio.run(run())


def test_mqtt_config_reuses_running_app_connection_and_preserves_device_messages(monkeypatch):
  async def run():
    client, source = mqtt_source(monkeypatch, {'config/dc': b'scene: pc\nstale: true\n'}, {'config/dc': 'dc'})
    arrived = asyncio.Event()

    class Consumer(AppService):
      async def _receive_config(self, topic, payload):
        await super()._receive_config(topic, payload)
        arrived.set()

    app = Consumer(name='consumer')
    app.connection = source['connection']
    task = asyncio.create_task(app.run())
    try:
      async with asyncio.timeout(2): await client.connected.wait()
      transport = app._mqtt_task
      devices = []
      await app.mqtt_listen(lambda topic, payload: devices.append(payload), 'devices/state')
      async with asyncio.timeout(2): await arrived.wait()
      arrived.clear()
      client.send('devices/state', b'on')
      client.send('config/dc', b'{"scene":"laptop"}')
      async with asyncio.timeout(2): await arrived.wait()
      assert glob_dict('dc') == {'scene': 'laptop'}
      assert devices == ['on']
      assert client.connections == 1
      assert app._mqtt_task is transport
      assert not client.closed
    finally:
      task.cancel()
      with pytest.raises(asyncio.CancelledError): await task
    assert client.closed
  asyncio.run(run())


def test_constructing_a_service_does_not_start_a_connection(monkeypatch):
  async def run():
    client, source = mqtt_source(monkeypatch, {}, {'config/dc': 'dc'})
    app = AppService(name='consumer')
    app.connection = source['connection']
    assert client.connections == 0
    assert app._mqtt_task is None
    assert glob_dict('') == {'local': {'keep': True}, 'consumer': {'config_mqtt': {'topics': source['topics']}}}
  asyncio.run(run())


def test_bad_config_on_existing_connection_fails_visibly(monkeypatch):
  async def run():
    client, source = mqtt_source(monkeypatch, {'config/dc': b'[1,2]'}, {'config/dc': 'dc'})
    app = AppService(name='consumer')
    app.connection = source['connection']
    async with asyncio.timeout(2):
      with pytest.raises(ExceptionGroup): await app.run()
    assert glob_dict('') == {'local': {'keep': True}, 'consumer': {'config_mqtt': {'topics': source['topics']}}}
    assert client.closed
    assert client.connections == 1
  asyncio.run(run())


@pytest.mark.parametrize('payload', [b'[1,2]', b'null', b'', b'key: [broken'])
def test_mqtt_bad_payload_fails_visibly_and_preserves_config(monkeypatch, payload):
  async def run():
    client, source = mqtt_source(monkeypatch, {'config/dc': payload}, {'config/dc': 'dc'})
    async with asyncio.timeout(2):
      with pytest.raises(ExceptionGroup): await AppService.from_mqtt(source)
    assert glob_dict('') == {'local': {'keep': True}, 'consumer': {'config_mqtt': {'topics': source['topics']}}}
    assert client.closed
  asyncio.run(run())


@pytest.mark.parametrize('topics', [{}, {'config/#': 'dc'}, {'a': 'dc', 'b': 'dc/scenes'}, {'a': '', 'b': 'dc'}])
def test_mqtt_rejects_indeterminate_or_overlapping_sources(topics):
  async def run():
    Env.from_dict({})
    with pytest.raises(ValueError):
      await AppService.from_mqtt({'connection': {'hostname': 'test-broker'}, 'topics': topics})
  asyncio.run(run())
