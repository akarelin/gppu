"""AppService: configuration from MQTT replaces a section of the app's own configuration, the same as loading it again."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gppu import AppService, mixin_Mqtt
from gppu import glob_dict


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
  """A broker holding *retained*, and the app's own configuration naming *topics*."""
  client = Client(retained)

  @asynccontextmanager
  async def connect(self):
    client.connections += 1
    client.connected.set()
    try: yield client
    finally: client.closed = True

  monkeypatch.setattr(mixin_Mqtt, '_mqtt_client', connect)
  return client, {'local': {'keep': True}, 'connection': {'hostname': 'test-broker'}, 'config_mqtt': {'topics': topics}}


def test_mqtt_startup_loads_every_topic_into_its_own_configuration_and_disconnects(monkeypatch):
  async def run():
    environment = glob_dict('')
    client, config = mqtt_source(monkeypatch,
      {'config/dc': b'scene: pc\n', 'config/ov': b'{"url":"https://ov"}'},
      {'config/dc': 'dc', 'config/ov': 'ov'})
    app = AppService(config=config)
    async with asyncio.timeout(2): await app.from_mqtt()
    assert app.my_dict('') == {**config, 'dc': {'scene': 'pc'}, 'ov': {'url': 'https://ov'}}
    assert glob_dict('') == environment
    assert client.subscriptions == [('config/dc', 1), ('config/ov', 1)]
    assert client.closed
    assert client.connections == 1
  asyncio.run(run())


def test_a_running_app_replaces_the_section_and_its_listener_reads_it_loaded(monkeypatch):
  async def run():
    client, config = mqtt_source(monkeypatch, {'config/dc': b'scene: pc\nstale: true\n'}, {'config/dc': 'dc'})
    seen, devices = asyncio.Queue(), []

    class Consumer(AppService):
      async def subscribe(self):
        await self.mqtt_listen(lambda topic, payload: seen.put_nowait(self.my_dict('dc')), 'config/dc')
        await self.mqtt_listen(lambda topic, payload: devices.append(payload), 'devices/state')

    app = Consumer(config={**config, 'dc': {'scene': 'none'}})
    task = asyncio.create_task(app.run())
    try:
      async with asyncio.timeout(2): assert await seen.get() == {'scene': 'pc', 'stale': True}
      transport = app._mqtt_task
      client.send('devices/state', b'on')
      client.send('config/dc', b'{"scene":"laptop"}')
      async with asyncio.timeout(2): assert await seen.get() == {'scene': 'laptop'}
      assert app.my('local/keep') is True
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
    client, config = mqtt_source(monkeypatch, {}, {'config/dc': 'dc'})
    app = AppService(config=config)
    assert client.connections == 0
    assert app._mqtt_task is None
    assert app.my_dict('') == config
  asyncio.run(run())


def test_bad_config_on_existing_connection_fails_visibly(monkeypatch):
  async def run():
    client, config = mqtt_source(monkeypatch, {'config/dc': b'[1,2]'}, {'config/dc': 'dc'})
    app = AppService(config=config)
    async with asyncio.timeout(2):
      with pytest.raises(ExceptionGroup): await app.run()
    assert app.my_dict('') == config
    assert client.closed
    assert client.connections == 1
  asyncio.run(run())


@pytest.mark.parametrize('payload', [b'[1,2]', b'null', b'', b'key: [broken'])
def test_mqtt_bad_payload_fails_visibly_and_preserves_config(monkeypatch, payload):
  async def run():
    client, config = mqtt_source(monkeypatch, {'config/dc': payload}, {'config/dc': 'dc'})
    app = AppService(config=config)
    async with asyncio.timeout(2):
      with pytest.raises(ExceptionGroup): await app.from_mqtt()
    assert app.my_dict('') == config
    assert client.closed
  asyncio.run(run())


@pytest.mark.parametrize('topics', [{}, {'config/#': 'dc'}])
def test_mqtt_rejects_indeterminate_sources(monkeypatch, topics):
  async def run():
    client, config = mqtt_source(monkeypatch, {}, topics)
    with pytest.raises(ExceptionGroup): await AppService(config=config).from_mqtt()
  asyncio.run(run())
