---
fileClass: Document
created: 2026-09-22
updated: 2026-09-22
generated: { by: Codex/GPT-6, at: 2026-09-22 }
---
# Locations, Containers and Provider operations

This document defines required behavior. Its authority is Alex's explanation in "Fix Dagster paths and duplicate UIDs", 2026-09-22, and the corrections in the current session. It is not a description of the present implementation.

## Location and Container

Locations form a tree. Each leaf references a Container. A Location includes its Provider and Connection; callers select a Location and invoke its operations. Provider and Connection are not separate arguments that an ingestion passes around. (Alex, recovered session: "Base objects are location and container", "provider, connection are all part of location", "Locations are a tree, each leaf references container".)

The URI boundary is `{location}/{path-at-location}` followed by `{folder}/{object}` within the referenced Container. Path-at-location selects the Container. Folders and objects returned from that Container are its contents, not automatically more configured Locations. (Alex, recovered session: "[location: {location}/{path-at-location}]/[container: {folder}/{obect}]"; current session: ordinary folder changes happen in Containers.)

For M365 user data, enumeration starts at the tenant Location, then users, then each user's data collections. The contacts Container contains contact folders, nested folders and contact objects. To Do lists and their tasks are enumerated within the user's To Do Container. Calendar collections contain calendars and events. A user drive contains folders and files. Graph endpoint spelling does not decide the configured Location/Container boundary. (Alex, recovered session: "User data for now", "Users, enumerated, than for each user, etc..."; current session: stable Locations and folder changes within Containers.)

An explicitly configured deeper Location may select a narrower Container boundary. This is a choice of scope, not a rule that every discovered folder becomes a Location. `file` can serve many Locations. `plaud://` is already the complete Provider-Connection Location. (Alex, current session, explicit file, Plaud and indexing-boundary requirements.)

Location configuration does not carry `access` or `storage` fields. Provider-specific access and file naming belong to the Provider implementation and its configuration. (Alex, recovered session, explicit rejection of those Location fields; current session: file Provider owns storage templates and paths.)

## DataObject

Reads return DataObjects: data with its URI and source identity. Binary content may include its original name and parent-object relationship. A DataObject contains no destination path. The name is `DataObject`, not `ProviderObject`. (Alex, recovered session: "DataObject", "It does not return providers"; current session: M365 returns objects and has no destination knowledge.)

## Provider responsibilities

Runtime-loaded Providers register supported URI schemas in memory. Schemas are not database records. URI construction and interpretation are reversible and select the corresponding Provider operation through the Location. (Alex, current session, runtime registration and reversible URI requirements.)

The M365 Provider handles authentication, token renewal, API requests, pagination, enumeration and API delta state. Authentication refresh tokens and data delta cursors have different purposes. A last-run timestamp must not replace the API's delta protocol. Reading requires only the source Location and the selected Container path. (Alex, recovered session and current session, source-interaction and cursor corrections.)

The file Provider accepts DataObjects, applies its configured naming and serialization templates, and writes their content. It resolves the filesystem details internally. The caller does not obtain an operating-system path to pass to a separate custom exporter. (Alex, recovered session: "Why does dagster need a path?" and "We are still working with files"; current session: file Provider owns storage templates.)

## gppu operation contract

The public classes are `Location`, `Container` and `DataObject`. Runtime registration belongs inside the catalog. `Providers` and `File` are not the caller-facing class model. Concrete implementations name the Location or Container they implement; Provider remains the implementation role bound within a Location. (Alex, current session: "So providers and file are bad class names in gppu.")

| Call | Input | Product |
|---|---|---|
| `catalog.location(uid)` | Configured Location identity | Location, with Provider and Connection bound |
| `location.ls()` | Selected Location | Child Location objects, constructed the same way as configured Locations |
| `location.walk()` | Selected Location | Each Location and its immediate children |
| `location.container(path)` | Path-at-location | Referenced Container |
| `container.ls(path)` | Path within the Container | Immediate folders and objects |
| `container.read(path)` | Object or path returned by listing | DataObject |
| `container.refresh(state, path)` | Caller-retained state and Container path | Changed DataObjects; the implementation updates state after successful consumption |
| `container.write(object)` | DataObject | Completed write; no return value |
| `container.delete(object)` | DataObject or relative path | Completed deletion; no return value |

These call names reflect Alex's corrections in the current session: "Yes, return Location objects"; "container has write, delete, read and ls - all makes sense". Runtime enumeration does not save Locations into configuration. Providers implement source operations; callers do not branch on Graph methods or file naming rules. Dagster retains opaque source state in successful materializations; M365 does not write SQL. Destination failure leaves the previous successful state available for the next run. No indexing or `lake://` implementation is implied. (Alex, recovered session, nested enumeration, native Dagster and file-only requirements; current session, SQL rejection.)
