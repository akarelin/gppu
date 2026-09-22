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
- Complete in production: M365 uses folder-scoped Contacts delta and reads full changed calendar events; source state stays in successful Dagster materializations.
- Complete in production: readable M365 names restored; colliding source copies reconstructed and verified from native snapshots; replaced copies preserved separately and native delta links retained.
- Complete in production: simple Markdown templates produce readable files with working source JSON links; regular M365 jobs succeed without downloading unchanged objects; schedules and the Plaud Markdown trigger are running.
- Complete in production: retain the original Telegram exporter, original destinations and schedules; exclude Telegram from the replacement Markdown flow. Alex, 2026-09-22: "D:\TextLake\Telegram Is perfect. Do not erase it."
- Complete in production: admin Location editor uses the flat tree and read-only Provider/Connection choices at Systems/admin_ui.

## Independent and unscoped

- Complete: production source writes, incremental reads, Markdown output and configuration API verified.
