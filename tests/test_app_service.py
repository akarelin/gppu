"""AppService: a retained MQTT section replaces its path in Env, the same as loading it again, and the app's own
configuration stays its own."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gppu import AppService, Env, mixin_Mqtt
from gppu import glob, glob_dict


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


@pytest.fixture(autouse=True)
def environment():
  """Each test starts from the Env it found, with one section of its own, and leaves it as it was."""
  previous, initialized = Env._my, Env.initialized
  Env._config_load({**previous, 'kept': {'by': 'test'}})
  yield
  Env._my, Env.initialized = previous, initialized


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


def test_mqtt_startup_loads_every_topic_into_env_and_disconnects(monkeypatch):
  async def run():
    client, config = mqtt_source(monkeypatch,
      {'config/dc': b'scene: pc\n', 'config/ov': b'{"url":"https://ov"}'},
      {'config/dc': 'display-control', 'config/ov': 'ov/server'})
    app = AppService(config=config)
    async with asyncio.timeout(2): await app.from_mqtt()
    assert glob_dict('display-control') == {'scene': 'pc'}
    assert glob('ov/server/url') == 'https://ov'
    assert glob_dict('kept') == {'by': 'test'}
    assert app.my_dict('') == config
    assert client.subscriptions == [('config/dc', 1), ('config/ov', 1)]
    assert client.closed
    assert client.connections == 1
  asyncio.run(run())


def test_a_running_app_replaces_the_section_and_its_listener_reads_it_loaded(monkeypatch):
  async def run():
    client, config = mqtt_source(monkeypatch, {'config/dc': b'scene: pc\nstale: true\n'}, {'config/dc': 'display-control'})
    seen, devices = asyncio.Queue(), []

    class Consumer(AppService):
      async def subscribe(self):
        await self.mqtt_listen(lambda topic, payload: seen.put_nowait(glob_dict('display-control')), 'config/dc')
        await self.mqtt_listen(lambda topic, payload: devices.append(payload), 'devices/state')

    app = Consumer(config=config)
    task = asyncio.create_task(app.run())
    try:
      async with asyncio.timeout(2): assert await seen.get() == {'scene': 'pc', 'stale': True}
      transport = app._mqtt_task
      client.send('devices/state', b'on')
      client.send('config/dc', b'{"scene":"laptop"}')
      async with asyncio.timeout(2): assert await seen.get() == {'scene': 'laptop'}
      assert app.my('local/keep') is True
      assert glob_dict('kept') == {'by': 'test'}
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
    client, config = mqtt_source(monkeypatch, {}, {'config/dc': 'display-control'})
    app = AppService(config=config)
    assert client.connections == 0
    assert app._mqtt_task is None
    assert app.my_dict('') == config
  asyncio.run(run())


def test_bad_config_on_existing_connection_fails_visibly(monkeypatch):
  async def run():
    client, config = mqtt_source(monkeypatch, {'config/dc': b'[1,2]'}, {'config/dc': 'display-control'})
    app = AppService(config=config)
    environment = glob_dict('')
    async with asyncio.timeout(2):
      with pytest.raises(ExceptionGroup): await app.run()
    assert glob_dict('') == environment
    assert client.closed
    assert client.connections == 1
  asyncio.run(run())


@pytest.mark.parametrize('payload', [b'[1,2]', b'null', b'', b'key: [broken'])
def test_mqtt_bad_payload_fails_visibly_and_preserves_env(monkeypatch, payload):
  async def run():
    client, config = mqtt_source(monkeypatch, {'config/dc': payload}, {'config/dc': 'display-control'})
    app = AppService(config=config)
    environment = glob_dict('')
    async with asyncio.timeout(2):
      with pytest.raises(ExceptionGroup): await app.from_mqtt()
    assert glob_dict('') == environment
    assert client.closed
  asyncio.run(run())


@pytest.mark.parametrize('topics', [{}, {'config/#': 'display-control'}])
def test_mqtt_rejects_indeterminate_sources(monkeypatch, topics):
  async def run():
    client, config = mqtt_source(monkeypatch, {}, topics)
    with pytest.raises(ExceptionGroup): await AppService(config=config).from_mqtt()
  asyncio.run(run())
