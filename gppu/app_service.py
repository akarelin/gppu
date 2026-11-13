"""gppu.app_service — AppService, an app that runs all the time and reloads its configuration from MQTT.

Its configuration's ``config_mqtt/topics`` maps each retained MQTT topic to the configuration
path the topic's payload replaces. When the service starts it listens on them; each message
replaces that subtree of ``Env`` through ``Env.update_config``, the same as loading it again.
``AppService.from_mqtt(source)`` reads the topics once, at startup, and returns.
"""
from __future__ import annotations

import yaml

from .gppu import Env
from .gppu import y2topic
from .iot import MqttApp


class AppService(MqttApp):
  """An MqttApp that runs all the time and reloads its configuration from MQTT.

  ``config_mqtt/topics`` in its configuration names the topics; each message replaces that
  subtree of ``Env``, and the app reads it with ``glob`` as usual.
  """

  _config_paths: dict[str, str]

  @staticmethod
  def _config_topics(topics: dict[str, str]) -> dict[str, str]:
    if not isinstance(topics, dict) or not topics:
      raise ValueError('MQTT configuration requires a topic to Env path mapping')
    for topic, path in topics.items():
      if not isinstance(topic, str) or not topic or '+' in topic or '#' in topic:
        raise ValueError('MQTT configuration topics must be exact topic names')
      if not isinstance(path, str) or (path and any(not part for part in path.split('/'))):
        raise ValueError('MQTT configuration paths must be slash paths or empty for the root')
    return dict(topics)

  @staticmethod
  async def from_mqtt(config: dict) -> None:
    """Load exact topics into their declared Env paths, then disconnect.

    config contains connection and topics (MQTT topic -> Env path).
    """
    await _StartupConfig(config).run()

  def config_topics(self) -> dict[str, str]:
    """MQTT topic -> the configuration path it replaces."""
    return self.my('config_mqtt/topics')

  async def __load(self) -> None:
    if not Env.initialized: raise RuntimeError('load the MQTT bootstrap with Env.from_env() first')
    self._config_paths = self._config_topics(self.config_topics())
    for topic in self._config_paths:
      await self.mqtt_listen(self._receive_config, topic, qos=1, raise_errors=True)

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    data = yaml.safe_load(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict): raise TypeError(f'MQTT configuration must be a mapping: {topic}')
    Env.update_config(data, self._config_paths[str(topic)])


class _StartupConfig(AppService):
  """Read retained startup configuration, then close the temporary connection."""

  def __init__(self, config: dict):
    connection, topics = config['connection'], self._config_topics(config['topics'])
    if not isinstance(connection, dict) or not connection.get('hostname'):
      raise ValueError('MQTT configuration requires connection.hostname')
    if not Env.initialized: raise RuntimeError('load the MQTT bootstrap with Env.from_env() first')
    super().__init__(name='config-mqtt')
    self.connection = connection
    self.topics = dict(topics)
    self.pending = set(topics)

  def config_topics(self) -> dict[str, str]: return self.topics

  async def _receive_config(self, topic: y2topic, payload: object) -> None:
    await super()._receive_config(topic, payload)
    self.pending.discard(str(topic))
    if not self.pending: self.stop()
