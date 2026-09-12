---
fileClass: Document
created: 2026-09-11
updated: 2026-09-11
generated: { by: Codex/GPT-6, at: '2026-09-11' }
---

# MQTT configuration

- Complete: Load configuration from MQTT through Env and identify changed configuration paths.
- Complete: Verify startup loading, subsequent changes, unchanged replays, errors, and ordinary YAML loading; focused tests and an isolated local Mosquitto check passed.
- Complete: Document usage, publish the gppu changes, and install the updated library in the shared Windows environment; the broker verification exercised the installed package.
- In progress: Apply Alex's clarification: console apps load once; live updates use an existing app MQTT connection only when requested. Verify connection reuse and startup disconnection, then publish and install.

## Requirements

- Alex, conversation of 2026-09-11: "update gppu so it supports configs from mqtt."
- Alex, conversation of 2026-09-11: "And Env or Environment object so it is aware of config cvhanges. Action will depend on which config changed."
- Alex, conversation of 2026-09-11: "Some systems restart to apply config - these you don't need to hot load."
- Alex, conversation of 2026-09-11: "depends on what app needs (console apps do not need reloading) and if app maintains mqtt connection (most do not)"

## Current task

Env owns configuration loading and change notifications. Env.from_mqtt disconnects after every declared topic has supplied startup configuration. Apps that need updates register mqtt_config subscriptions on their existing mixin_Mqtt/MqttApp transport. Registration does not start a connection. Consumers choose their response to a change. No application restart, file deployment, or device action belongs in the loader.

The bootstrap uses the existing connection mapping and an exact MQTT topic to Env path mapping. The documentation uses config_mqtt as an example section name. Received YAML/JSON mappings replace their declared subtree. Duplicate messages do not generate changes. Invalid configuration fails visibly. The whole configuration remains accessible through Env.

## Separate preparation

- Complete: [OV client defaults, Jinja-driven configuration, and Display Control as another Y2 compiler](D:/Work/09/11/host-maintenance/ov-client-jinja-fact-check.codex.md); preparation only, as Alex requested.
