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
- Partially done: M365 implements API enumeration and delta state without SQL; the folder-scoped Contacts delta correction still needs production deployment.
- In progress: finish the Dagster source-to-JSON and JSON-to-Markdown flow; the shared Markdown trigger is stopped after Alex's Telegram correction.
- Complete in production: retain the original Telegram exporter, original destinations and schedules; exclude Telegram from the replacement Markdown flow. Alex, 2026-09-22: "D:\TextLake\Telegram Is perfect. Do not erase it."
- Complete in production: admin Location editor uses the flat tree and read-only Provider/Connection choices at Systems/admin_ui.

## Independent and unscoped

- Pending: production verification.
