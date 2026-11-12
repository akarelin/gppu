---
fileClass: Document
created: 2026-09-21
updated: 2026-09-21
generated: { by: Codex/GPT-5, at: 2026-09-21 }
---

# Location configuration contract

The required Location and Container model is defined in [providers.md](providers.md). This document describes that contract, not the existing implementation.

The catalog supplies the Location tree. A Location binds its Provider and Connection. A leaf references a Container; the Container holds folders and DataObjects. Selecting and traversing configured Locations does not read Container contents or run indexing. (Alex, "Fix Dagster paths and duplicate UIDs", 2026-09-22.)

`catalog.location(uid)` returns a Location. `location.ls()` enumerates its child Location objects through the same constructor used for configured Locations. `location.container(path)` selects a Container using path-at-location. Applications call the Location/Container operations. (Alex, same session: Provider plus Connection is Location; reading invokes the Location's operation on the object's path; current session: "Yes, return Location objects".)

Location declarations contain identity, parentage and the path selecting their Container. Provider and Connection choices configure the Location. `access` and `storage` are not Location fields. Provider schemas come from loaded runtime code. Provider-specific file access and naming remain Provider configuration. (Alex, same session, explicit field rejection; current session, runtime schema and file Provider requirements.)

The configuration API returns a flat representation of the tree with parent references, so the UI builds one Location control. It does not expose a second representation of the same Location under a `/children` resource. Provider and Connection endpoints supply read-only choices for that control. Container enumeration is a separate operation and never creates Location configuration as a side effect. (Alex, same session, Location tree/API and dropdown requirements.)

