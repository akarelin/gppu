# W11 — Windows 11 Utilities

[![W11](https://github.com/akarelin/gppu/actions/workflows/w11.yml/badge.svg)](https://github.com/akarelin/gppu/actions/workflows/w11.yml)

Windows 11 utilities and diagnostics. Windows-only (Intel/amd64). Part of the [gppu](../README.md) repository.

## Installation

```bash
# From source
cd w11 && pip install -e .

# Binary release (Windows x64)
# Download from https://github.com/akarelin/gppu/releases?q=w11
```

## Tools

### w11-events

TUI application for Windows Event Viewer analysis. Queries event logs, deduplicates noise (45K NVIDIA crashes become 1 line), classifies errors by category/source rules, and tracks known error sources.

Full documentation: [w11-events.md](w11-events.md)

```bash
w11 events                          # TUI
python w11-events.py --stats        # recalculate stats, no TUI
python w11-events.py --days 7       # override time window
python w11-events.py --clear-logs   # clear all configured logs (admin)
```

**Files:**
- `w11-events.py` — main application
- `w11-events.yaml` — config (logs, level, days)
- `error_rules.yaml` — category/source rules (`category/`, `/source`, `category/source` pairs)
- `event_categories.yaml` — event type taxonomy

**TUI keybindings:** `q` quit, `d` theme, `s` stats, `r` refresh, `c` clear logs, `e` export history, `w` export errors, `a` add rule, `o` overlap analysis

### w11-onedrive

OneDrive for Business sync diagnostics & conflict analysis TUI.

Full documentation: [w11-onedrive.md](w11-onedrive.md)

```bash
w11 onedrive                                # interactive mode selector
python w11-onedrive.py diag                 # sync diagnostics
python w11-onedrive.py diag --watch         # auto-refresh
python w11-onedrive.py conflicts            # conflict analysis
```

Reference: [OD4B-Sync-Diagnostics.md](OD4B-Sync-Diagnostics.md) — OneDrive for Business troubleshooting (log locations, key fields, reset procedure)

## Dependencies

- [gppu](../README.md) — configuration, logging, utilities
- [textual](https://textual.textualize.io/) — TUI framework
- PyYAML

## Config Pattern

Uses [gppu](../README.md) `Env` for configuration:
```python
Env(name='w11', app_path=APP_DIR)
Env.load()
```
Resolves config path per OS. YAML `!include` for modular configs.
