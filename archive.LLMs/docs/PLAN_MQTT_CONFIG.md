---
fileClass: Document
created: 2026-09-11
updated: 2026-09-12
generated: { by: Codex/GPT-6, at: '2026-09-12' }
---

# MQTT configuration

Historic plan, completed with [gppu 3.6.5](https://github.com/akarelin/gppu/releases/tag/gppu/v3.6.5) on 2026-09-12. The release and gppu/latest contain the changes, and the released package is installed and verified in the shared Windows environment. [Current usage](mqtt-config.md) describes the released API.

- Complete: Load configuration from MQTT through Env and identify changed configuration paths.
- Complete: Verify startup loading, subsequent changes, unchanged replays, errors, and ordinary YAML loading; focused tests and an isolated local Mosquitto check passed.
- Complete: Document usage and push the gppu source changes.
- Complete: Apply Alex's clarification: console apps load once; live updates use an existing app MQTT connection only when requested. Connection reuse and startup disconnection passed focused tests and released-package broker verification.
- Complete: Publish gppu 3.6.5, verify gppu/latest and both wheel downloads, install from gppu/latest, and finalize the closeout.

## Requirements

- Alex, conversation of 2026-09-11: "update gppu so it supports configs from mqtt."
- Alex, conversation of 2026-09-11: "And Env or Environment object so it is aware of config cvhanges. Action will depend on which config changed."
- Alex, conversation of 2026-09-11: "Some systems restart to apply config - these you don't need to hot load."
- Alex, conversation of 2026-09-11: "depends on what app needs (console apps do not need reloading) and if app maintains mqtt connection (most do not)"
- Alex, conversation of 2026-09-12: "Document finalize and close"
- Alex, conversation of 2026-09-12: "gppu does not have dev builds. You are mistaken"
- Alex, conversation of 2026-09-12: "Release, document, finalize and close"

## Delivered behavior

Env owns configuration loading and change notifications. Env.from_mqtt disconnects after every declared topic has supplied startup configuration. Apps that need updates register mqtt_config subscriptions on their existing mixin_Mqtt/MqttApp transport. Registration does not start a connection. Consumers choose their response to a change. No application restart, file deployment, or device action belongs in the loader.

The bootstrap uses the existing connection mapping and an exact MQTT topic to Env path mapping. The documentation uses config_mqtt as an example section name. Received YAML/JSON mappings replace their declared subtree. Duplicate messages do not generate changes. Invalid configuration fails visibly. The whole configuration remains accessible through Env.

## Separate preparation

- Complete: [OV client defaults, Jinja-driven configuration, and Display Control as another Y2 compiler](D:/Work/09/11/host-maintenance/ov-client-jinja-fact-check.codex.md); preparation only, as Alex requested.

## Closeout

The release workflow's Linux and TUI checks passed on 2026-09-12. The versioned and latest tags identify the released code, their wheel downloads are identical, and the installed package reports 3.6.5. Broker verification against that released installation confirmed retained startup delivery, selective notifications, connection reuse, normal device messages, and clean disconnection. [Final state and remaining scope](D:/Work/09/12/host-maintenance/host-maintenance-closeout.codex.md) records the evidence and the unapplied harness and compiler preparation.
