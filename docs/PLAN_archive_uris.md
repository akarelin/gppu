---
fileClass: Document
created: 2026-09-23
updated: 2026-09-23
generated: { by: codex/gpt-6, at: 2026-09-23 }
---

# Archive URI correction

Historic plan; completed 2026-09-23.

Alex’s requirement: [archive-uri-requirements.codex.md](D:/Work/09/23/gppufs-configuration-spec/archive-uri-requirements.codex.md).

- Complete: identify archive URI use in browsing, byte access and indexes.
- Complete: use ordinary container paths for archives and their members. Each archive’s file metadata and child listing share its single address; access selects the archive filesystem internally.
- Complete: verify archive navigation, direct and nested reads, refresh, rename recovery, catalog routing, external indexes and SQLite caches. The affected filesystem, Container, CLI and TUI checks pass in dev.
- Complete: update the structured documentation and publish the change. The YAML retains Alex’s requirement as an annotation; its views validate against current source, and the revised byte-access flow renders in Mermaid.

The package import repair removes stale imports of lifecycle classes already renamed to private classes; it preserves the class definitions and enables the URI checks.
