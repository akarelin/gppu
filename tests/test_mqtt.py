import asyncio
from types import SimpleNamespace

import pytest

from gppu import AsyncApp
from gppu.mqtt import Mqtt, config_topics, topic_matches


class Broker:
  """A fake aiomqtt client: records subscribe and publish, delivers what ``send`` queues."""
  def __init__(self):
    self.queue: asyncio.Queue = asyncio.Queue()
    self.subscribed, self.published = [], []

  async def __aenter__(self): return self
  async def __aexit__(self, *exc): return False
  async def subscribe(self, topic, qos=0): self.subscribed.append((topic, qos))
  async def publish(self, topic, payload, qos=0, retain=False, properties=None): self.published.append((topic, payload, retain))

  def send(self, topic, payload, retain=False): self.queue.put_nowait(SimpleNamespace(topic=topic, payload=payload.encode(), retain=retain))

  @property
  async def messages(self):
    while True: yield await self.queue.get()


class FakeMqtt(Mqtt):
  scheme = 'fake-mqtt'

  def __init__(self, *a, **kw):
    super().__init__(*a, **kw)
    self.broker = Broker()

  def _client_for(self, status): return self.broker


CONFIG = {'connections': {'mqtt-test': {'provider': 'fake-mqtt', 'hostname': 'i2'}}}


def test_topic_matching():
  assert topic_matches('a/b/c', 'a/+/c') and topic_matches('a/b/c', 'a/#') and topic_matches('a', 'a/#')
  assert not topic_matches('a/b', 'a/+/c') and not topic_matches('$SYS/x', '#')


def test_config_topics_reject_overlap():
  with pytest.raises(ValueError): config_topics({'t/1': 'dc', 't/2': 'dc/scenes'})
  with pytest.raises(ValueError): config_topics({'t/+': 'dc'})


def test_listen_before_serve_then_publish_and_config(env):
  env(CONFIG | {'dc': {'old': 1}})
  seen = []

  class Service(AsyncApp):
    async def main(self, mqtt: FakeMqtt) -> dict:
      mqtt.connection['status_topic'] = 'svc/status'
      await mqtt.listen(lambda topic, payload: seen.append((str(topic), payload)), 'dev/+/state')
      self._spawn(mqtt.serve())
      await mqtt.connected.wait()
      mqtt.broker.send('cfg/dc', 'scenes: {work: 1}', retain=True)
      await asyncio.wait_for(mqtt.config({'cfg/dc': 'dc'}, wait=True), 1)
      mqtt.broker.send('dev/tv/state', '{"on": true}')
      mqtt.broker.send('other/tv/state', 'x')
      await mqtt.publish('dev/tv/set', {'on': False}, retain=True)
      while not seen: await asyncio.sleep(0)
      await self.stop()
      return {'subscribed': mqtt.broker.subscribed, 'published': mqtt.broker.published}

  result = asyncio.run(Service().invoke())
  assert seen == [('dev/tv/state', {'on': True})]
  assert result['subscribed'] == [('dev/+/state', 0), ('cfg/dc', 1)]
  assert ('svc/status', 'online', True) in result['published'] and ('dev/tv/set', '{"on": false}', True) in result['published']
  assert ('svc/status', 'offline', True) in result['published']
  from gppu import Env
  assert Env.glob('dc/scenes/work') == 1 and 'old' not in Env.glob_dict('dc')
