# gppu: environment, state, runtime

Working notes of an agent session, 2026-11-21. Findings from code, each with where it was seen. Not a specification and not rules.

Alex's frame: there are three things, environment, state and runtime; everything else is access to them.

## What the history records as settled (commit messages, gppu repository)
Environment
- Two environments, RAN and Creekview; gppu hard-codes the two files' paths, the only two use cases (`c8e14e1`). A third, ETL, is foreseen (`45b4e29`).
- They differ only by init provider (`e73d7a0`).
- Env loads one of the two as gppu is imported, and no app names it (`1fe3fee`, `70b53ed`). An app that declares another environment raises (`7416b31`).
- On a host without the repository the environment, or the part an app needs, is read from MQTT (`21cfcfc`).
Runtime
- The runtime, not State's managers, loads a bunch of objects from a YAML list or a folder (`18d9cd8`).
- Refreshing belongs to the runtime and is configured, each object in the one way known for it; there is no state manager, only the runtime (`dcac586`).
State
- State is a lookup from identity to entity (Alex, 2026-11-21: there is a lot more to Y2's State than that); identity comes from configuration; input and output templates are an object's representation (`dcac586`).
- State keeps the MQTT broker, and gppu offers a simple way for an app to keep its own state (`4f3e67d`).
- Environment and State are single instances, as in Y2 (`2a86568`).

## Environment
- One shared object per program, read with `glob`. Earlier gppu: class `Env`, `IoT/archive/ads/gppu-storm/gppu_users/gppu/gppu.py:1014`. Checkout: `Env`, `gppu/gppu.py:1611`.
- An object's own part was held apart from its data, in `_my`, read with `my` (`...gppu_users/gppu/gppu.py:1277-1289`).
- Checkout: `my` reads the object's data, and `App` loads the environment and the command line into its data (`gppu/gppu.py:1532`, `1554-1572`).

## Runtime
- Runtime exists under other names. The classes named `AsyncApp` (objects from configuration, loop, timers), Y2's `App` (listeners), `Y2.start` (apps from `y2/apps`), `_Runtime` (registries, restart), `State` (loop, broker client) and each state manager are pieces of it, not apps that contain it.
- Standalone apps: the script makes the app and calls its work itself (`IoT/any2mqtt/lastfile2mqtt.py:122-125`, `RAN/Skills/devops/scripts/kea.py:50`).
- Y2 added two steps of its own, refresh and publish (`.../Y2/y2util.py:223-236`). In the checkout they are ordinary methods.

## State
- Y2: `State` in `y2/y2entity.py:1717`, not kept across restarts; entities start as `newborn`.
- gppu has a DC that stores and loads its data by class name and key, `_PersistentDC` (`gppu/data.py:144`). Its only users found are an archived experiment (`IoT/archive/Y2excess3/excess/y2pdc`) and gppu's tests.
- Apps that keep something across runs do it themselves: `RAN/Hosts/rewrite-commits/rewrite_commits.py:98-113`; Ecobee's token and Nest's session in Y2.

## Resolving objects (Alex, 2026-11-21)
- State and runtime, and the importance of resolving objects, go together.
- Objects have given names: a path, a slug, or kebab case.
- An action is the example of an object with a globally unique name: knowing its path, an action can always be looked up.
- Entities are one use case in Y2, with the eid notation. Actions, paths, hosts (kebab case) and anything else with a globally unique name can be referenced in configuration by that name.
- A name is resolved automatically into whatever it needs to resolve into when the code is run. That is why the code that runs a sequence is so short.
- One object talking to another is the less common use case. The more common one is something like an admin UI built on top of the objects in runtime.
- The point is not that configuration refers to objects by name. It is that every notable object has a stable, globally unique ID, so it can always be found: to get the state of a sensor, you know how to find it.
- The globally unique ID is what enables state: state is possible because the ID exists.
- It also makes complex configurations simple: anything can be referred to by its globally unique, human-readable ID. That is why configurations are so simple, especially for actions.

## DC and REST (Alex, 2026-11-21)
- The REST mixin does not work and gets in the way: comment it out or mark it deprecated.
- Objects are derived from DC, and so they do not need constructors.

## The basic example (Alex, 2026-11-21)
- A Tuya light entity and an Insteon light entity: two lights, different approach, same code. The difference between them, seen from environment, runtime and state, in code and in configuration, is the example of the two relations between an object and its runtime.
- Deprecated, poorly implemented code is not evidence about the architecture.
- There is no such thing as a row; it is not an object of this architecture.
- The difference between the Tuya and the Insteon light is neither templates nor runtime. Hue against Insteon, Tuya or Kasa shows it.
- There are no pushed or pulled objects in this approach; pushing or pulling objects is a violation of it.
- Insteon's device and Y2's device are the same thing. The difference between a device and an entity is superficial: name, members and entities.

## Runtime and state (Alex, 2026-11-21)
- There are events in runtime, and there are no events in state.
- `members` contains references. `members` is not state, and `entities` is not runtime and not environment.
- Understanding is to come from analysing the working code, not from markdown files of unknown origin; `SPEC.md` is not to be read.
