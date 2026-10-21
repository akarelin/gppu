"""gppu.app_service — AppService, an app that runs all the time and reloads its configuration from MQTT.

Its configuration's ``config_mqtt/topics`` maps each retained MQTT topic to the configuration
path the topic's payload replaces. When the service starts it listens on them; each message
replaces that subtree of ``Env``, and the callbacks registered with ``on_change`` hear which
paths changed. ``AppService.from_mqtt(source)`` reads the topics once, at startup, and returns.
"""
from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from copy import deepcopy

import yaml

from .gppu import Env
from .gppu import y2path, y2topic
from .iot import MqttApp


class AppService(MqttApp):
  """An MqttApp that runs all the time and reloads its configuration from MQTT.

  ``config_mqtt/topics`` in its configuration names the topics. Register what reacts to a
  change with ``AppService.on_change(callback, path)``; the configuration is already replaced
  when a callback runs, so it reads ``Env`` as usual.
  """

  changed_paths: frozenset[str] = frozenset()
  _listeners: list[tuple[str, Callable[[frozenset[str]], None]]] = []
  _config_paths: dict[str, str]

  @staticmethod
  def _config_changes(before: dict, after: dict, prefix: str = '') -> frozenset[str]:
    changed = set()
    for key in before.keys() | after.keys():
      path = f'{prefix}/{key}' if prefix else str(key)
      if key not in before or key not in after:
        changed.add(path)
      elif isinstance(before[key], dict) and isinstance(after[key], dict):
        changed.update(AppService._config_changes(before[key], after[key], path))
      elif isinstance(before[key], list) and isinstance(after[key], list):
        if json.dumps(before[key], sort_keys=True) != json.dumps(after[key], sort_keys=True): changed.add(path)
      elif type(before[key]) is not type(after[key]) or before[key] != after[key]:
        changed.add(path)
    return frozenset(changed)


  @staticmethod
  def _config_topics(topics: dict[str, str]) -> dict[str, str]:
    if not isinstance(topics, dict) or not topics:
      raise ValueError('MQTT configuration requires a topic to Env path mapping')
    paths = []
    for topic, path in topics.items():
      if not isinstance(topic, str) or not topic or '+' in topic or '#' in topic:
        raise ValueError('MQTT configuration topics must be exact topic names')
      if not isinstance(path, str) or (path and any(not part for part in path.split('/'))):
        raise ValueError('MQTT configuration paths must be slash paths or empty for the root')
      if any(not path or not other or path == other or path.startswith(other + '/')
             or other.startswith(path + '/') for other in paths):
        raise ValueError('MQTT configuration paths must not overlap')
      paths.append(path)
    return dict(topics)

  @staticmethod
  def on_change(callback: Callable[[frozenset[str]], None], path: str | y2path = '') -> Callable[[], None]:
    """Observe changed slash paths after loading; return a callable to unsubscribe.

    Callbacks are synchronous. The consumer decides how to apply each change.
    Registrations survive configuration reloads and Env.reset().
    """
    if inspect.iscoroutinefunction(callback): raise TypeError('configuration change callbacks must be synchronous')
    entry = (str(path).strip('/'), callback)
    AppService._listeners.append(entry)
    def unsubscribe():
      if entry in AppService._listeners: AppService._listeners.remove(entry)
    return unsubscribe

  @staticmethod
  def update_config(data: dict, path: str | y2path = '') -> None:
    """Replace one configuration subtree; an empty path replaces the whole config."""
    if not isinstance(data, dict): raise TypeError('configuration must be a mapping')
    updated = deepcopy(Env.data) if path else data
    if path:
      node = updated
      *parents, key = y2path(path)
      for parent in parents:
        if parent not in node: node[parent] = {}
        node = node[parent]
        if not isinstance(node, dict): raise TypeError(f'configuration parent is not a mapping: {path}')
      node[key] = data
    changed = AppService._config_changes(Env.data, updated)
    AppService.changed_paths = changed
    if Env.initialized and not changed: return
    Env._load_dict(updated)
    for watched, callback in tuple(AppService._listeners):
      relevant = frozenset(key for key in changed if not watched or key == watched
                           or key.startswith(watched + '/') or watched.startswith(key + '/'))
      if relevant: callback(relevant)

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
    AppService.update_config(data, self._config_paths[str(topic)])


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
