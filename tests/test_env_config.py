"""Configuration replacement and change routing through the public Env API."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gppu import Env
from gppu.iot import _MqttConfig


@pytest.fixture(autouse=True)
def environment():
  previous, initialized = Env.data, Env.initialized
  listeners = Env._listeners
  Env._listeners = []
  Env.reset()
  yield
  Env.reset()
  Env._listeners = listeners
  Env.data, Env.initialized = previous, initialized


def test_yaml_reload_reports_only_affected_paths(tmp_path):
  path = tmp_path / 'config.yaml'
  path.write_text('dc:\n  scene: pc\n  removed: true\nother: 1\n')
  Env.from_env(name='consumer', app_path=tmp_path)
  assert Env.glob_dict('') == {'dc': {'scene': 'pc', 'removed': True}, 'other': 1}
  seen, unrelated = [], []
  unsubscribe = Env.on_change(seen.append, 'dc')
  Env.on_change(unrelated.append, 'other')
  path.write_text('dc:\n  scene: laptop\nother: 1\n')
  Env.from_env(name='consumer', app_path=tmp_path)
  assert seen == [frozenset({'dc/scene', 'dc/removed'})]
  assert unrelated == []
  Env.from_env(name='consumer', app_path=tmp_path)
  assert len(seen) == 1
  assert Env.changed_paths == frozenset()
  unsubscribe()
  Env.update_config({'scene': 'mac'}, 'dc')
  assert len(seen) == 1


def test_subtree_replacement_preserves_other_config_and_reports_removal():
  Env.from_dict({'dc': {'scene': 'pc', 'stale': True}, 'ov': {'url': 'https://ov'}})
  seen = []
  Env.on_change(seen.append, 'dc/stale')
  Env.update_config({'scene': 'pc'}, 'dc')
  assert Env.glob_dict('') == {'dc': {'scene': 'pc'}, 'ov': {'url': 'https://ov'}}
  assert seen == [frozenset({'dc/stale'})]
  Env.update_config({'ov': {'url': 'https://ov'}})
  assert seen[-1] == frozenset({'dc'})


def test_invalid_config_does_not_replace_current_values():
  Env.from_dict({'dc': {'scene': 'pc'}})
  seen = []
  Env.on_change(seen.append)
  with pytest.raises(TypeError, match='mapping'): Env.update_config(['bad'])
  with pytest.raises(TypeError, match='mapping'): Env.update_config({'trace_rules': False})
  assert Env.glob_dict('') == {'dc': {'scene': 'pc'}}
  assert seen == []


def test_scalar_type_changes_are_reported():
  Env.from_dict({'enabled': False})
  Env.update_config({'enabled': 0})
  assert Env.changed_paths == frozenset({'enabled'})
  Env.update_config({'values': [False]})
  Env.update_config({'values': [0]})
  assert Env.changed_paths == frozenset({'values'})


def test_removing_configured_trace_rules_clears_them():
  from gppu import TRACE_RULES
  previous = dict(TRACE_RULES)
  try:
    Env.from_dict({'trace_rules': {'all': True}})
    Env.update_config({})
    assert TRACE_RULES == {}
    assert Env.changed_paths == frozenset({'trace_rules'})
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

  async def subscribe(self, topic, qos):
    self.subscriptions.append((topic, qos))
    if topic in self.retained: self.send(topic, self.retained[topic])

  def send(self, topic, payload):
    self.messages.queue.put_nowait(SimpleNamespace(topic=topic, payload=payload))


def mqtt_source(monkeypatch, retained, topics):
  client = Client(retained)

  @asynccontextmanager
  async def connect(self):
    try: yield client
    finally: client.closed = True

  monkeypatch.setattr(_MqttConfig, '_mqtt_client', connect)
  Env.from_dict({'local': {'keep': True}})
  return client, {'connection': {'hostname': 'test-broker'}, 'topics': topics}


def test_mqtt_startup_loads_all_declared_topics_and_disconnects(monkeypatch):
  async def run():
    client, source = mqtt_source(monkeypatch,
      {'config/dc': b'scene: pc\n', 'config/ov': b'{"url":"https://ov"}'},
      {'config/dc': 'dc', 'config/ov': 'ov'})
    async with asyncio.timeout(2): await Env.from_mqtt(source)
    assert Env.glob_dict('') == {'local': {'keep': True}, 'dc': {'scene': 'pc'}, 'ov': {'url': 'https://ov'}}
    assert client.subscriptions == [('config/dc', 1), ('config/ov', 1)]
    assert client.closed
  asyncio.run(run())


def test_mqtt_watch_routes_changes_ignores_replay_and_stops(monkeypatch):
  async def run():
    client, source = mqtt_source(monkeypatch, {'config/dc': b'scene: pc\nstale: true\n'}, {'config/dc': 'dc'})
    seen, other = [], []
    ready = asyncio.Event()
    def changed(paths):
      seen.append(paths)
      ready.set()
    Env.on_change(changed, 'dc')
    Env.on_change(other.append, 'ov')
    task = asyncio.create_task(Env.from_mqtt(source, watch=True))
    try:
      async with asyncio.timeout(2): await ready.wait()
      ready.clear()
      client.send('config/dc', b'scene: pc\nstale: true\n')
      client.send('config/dc', b'{"scene":"laptop"}')
      async with asyncio.timeout(2): await ready.wait()
      assert seen == [frozenset({'dc'}), frozenset({'dc/scene', 'dc/stale'})]
      assert other == []
      assert Env.glob_dict('dc') == {'scene': 'laptop'}
    finally:
      task.cancel()
      with pytest.raises(asyncio.CancelledError): await task
    assert client.closed
  asyncio.run(run())


@pytest.mark.parametrize('payload', [b'[1,2]', b'null', b'', b'key: [broken'])
def test_mqtt_bad_payload_fails_visibly_and_preserves_config(monkeypatch, payload):
  async def run():
    client, source = mqtt_source(monkeypatch, {'config/dc': payload}, {'config/dc': 'dc'})
    async with asyncio.timeout(2):
      with pytest.raises(ExceptionGroup): await Env.from_mqtt(source)
    assert Env.glob_dict('') == {'local': {'keep': True}}
    assert client.closed
  asyncio.run(run())


@pytest.mark.parametrize('topics', [{}, {'config/#': 'dc'}, {'a': 'dc', 'b': 'dc/scenes'}, {'a': '', 'b': 'dc'}])
def test_mqtt_rejects_indeterminate_or_overlapping_sources(topics):
  async def run():
    Env.from_dict({})
    with pytest.raises(ValueError):
      await Env.from_mqtt({'connection': {'hostname': 'test-broker'}, 'topics': topics})
  asyncio.run(run())
