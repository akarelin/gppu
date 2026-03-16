# Win11

Windows 11 utilities and diagnostics for Alex-PC (KARELIN domain).

## Tools

### w11-events

TUI application for Windows Event Viewer analysis. Queries event logs, deduplicates noise (45K NVIDIA crashes become 1 line), classifies errors by category/source rules, and tracks known error sources.

```bash
python w11_events.py              # TUI
python w11_events.py --stats      # recalculate stats, no TUI
python w11_events.py --days 7     # override time window
python w11_events.py --clear-logs # clear all configured logs (admin)
```

**Files:**
- `w11_events.py` — main application
- `w11_events.yaml` — config (logs, level, days)
- `error_rules.yaml` — category/source rules (`category/`, `/source`, `category/source` pairs)
- `Alex-PC.yaml` — auto-generated stats per host
- `SPEC.md` — full specification

**TUI keybindings:** `q` quit, `d` theme, `s` stats, `r` refresh, `c` clear logs, `e` export history, `w` export errors, `a` add rule, `o` overlap analysis

**Dependencies:** gppu, textual, PyYAML

### Watch-EventLog.ps1

PowerShell version (predecessor). Real-time event log watcher with color-coded output, dedup, and CSV/JSON export. Standalone, no dependencies.

```powershell
.\Watch-EventLog.ps1                              # default: warnings+, last 10 days
.\Watch-EventLog.ps1 -LogName System -Level Error  # specific log/level
.\Watch-EventLog.ps1 -ExportPath events.csv        # export
.\Watch-EventLog.ps1 -NoDeDup                      # disable dedup
```

### OneDrive Diagnostics

- `onedrive-diag.py` — OneDrive sync diagnostics tool
- `OD4B-Sync-Diagnostics.md` — OneDrive for Business troubleshooting reference (log locations, key fields, reset procedure)

### pc-control

PC control utilities (placeholder).

## Config Pattern

Uses [gppu](../../gppu) `Env` for configuration:
```python
Env(name='w11_events', app_path=Path('RAN/Win11'))
Env.load()
```
Resolves config path per OS. YAML `!include` for modular configs.
