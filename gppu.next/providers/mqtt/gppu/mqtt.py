"""gppu.mqtt — provider: an MQTT broker through aiomqtt.

Replaces MqttApp and _MqttConfig: an AsyncApp asks for a broker and runs its connection in its own TaskGroup.

    connections:
      mqtt-i2: {provider: gppu.mqtt.Mqtt, hostname: i2, port: 1883}

    class Brultech(AsyncApp):
      async def main(self, mqtt: Mqtt = 'mqtt-i2'):
        await mqtt.listen(self.on_reading, 'brultech/+/raw')
        self._spawn(mqtt.serve())

The body of gppu/iot.py mixin_Mqtt moves here unchanged — reconnect loop, per-topic callbacks, retained
filtering, configuration over MQTT (``config``, formerly ``mqtt_config`` and ``Env.from_mqtt``). The mock-up shows the
surface only.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from gppu import Provider

MqttCallback = Callable[[str, Any], Awaitable[None] | None]


class Mqtt(Provider):
  """One broker connection: ``hostname``, ``port``, ``username``, ``password``, ``identifier``."""
  scheme = 'mqtt'

  async def serve(self) -> None:
    """Hold the connection, reconnecting, and deliver messages to the listeners; run it with the app's ``_spawn``."""
    raise NotImplementedError('mixin_Mqtt._mqtt_loop moves here')

  async def listen(self, callback: MqttCallback, topic: str, *, ignore_retained: bool = False, qos: int = 0) -> None:
    raise NotImplementedError('mixin_Mqtt.mqtt_listen moves here')

  async def publish(self, topic: str, payload: Any = '', *, retain: bool = False, qos: int = 0) -> None:
    raise NotImplementedError('mixin_Mqtt.mqtt_publish moves here')

  async def config(self, topics: dict[str, str]) -> None:
    """Receive configuration subtrees on these topics into Env (topic -> Env path)."""
    raise NotImplementedError('mixin_Mqtt.mqtt_config moves here')
