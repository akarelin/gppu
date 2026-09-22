---
fileClass: Document
created: 2026-09-22
updated: 2026-09-22
generated: { by: Codex/GPT-6, at: 2026-09-22 }
---
# Location and Container correction

Requirements: Alex's messages recovered from "Fix Dagster paths and duplicate UIDs", recorded in D:\Work\09\22\location-container\requirements.codex.md.

- Complete: document the intended gppu/API model and the intended Dagster-to-gppu ingestion map from Alex's explanation; production code is not design authority.
- Complete in dev: Location.ls returns Location objects, Container exchanges typed DataObjects, FileContainer resolves configured paths for read/write/delete.
- Complete in dev: M365 implements API enumeration and delta state without SQL; native folder metadata is preserved.
- In progress: finish the Dagster source-to-JSON and JSON-to-Markdown flow and its declared configuration.
- Complete in dev: admin Location editor uses the flat tree and read-only Provider/Connection choices.

## Independent and unscoped

- Pending: production verification.
