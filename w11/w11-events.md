# w11-events — Specification

## Overview

Python TUI application (`w11_events.py`) that queries Windows Event Viewer logs, deduplicates events, classifies them by category/source rules, and displays them in an interactive terminal UI. Uses `gppu` for config management and `textual` for TUI.

## Location

`D:\Dev\RAN\Win11\`

## Dependencies

- **gppu** — config loading (`Env`, `dict_from_yml`, `dict_to_yml`, YAML `!include`)
- **textual** — TUI framework (DataTable, RichLog, panels)
- **wevtutil** — Windows event log queries (rendered XML)
- **PyYAML** — stats file I/O

## Configuration

**`w11_events.yaml`** — main config loaded via gppu `Env(name='w11_events', app_path=Path('RAN/Win11'))`:
- `logs` — list of Windows event log channels (Application, System, Security, Kernel-PnP/Configuration)
- `level` — minimum severity (Warning default)
- `days` — history window (30 default)
- `dedup` — global dedup on/off
- `max_message_length` — truncation limit
- `error_rules` — `!include error_rules.yaml`

**`error_rules.yaml`** — combined category/source rule definitions (single file).

## Rule Format: `category/source` Pairs

Key format determines type:

| Key | Type | Purpose |
|-----|------|---------|
| `app-crash/` | Category | Error pattern definition — HOW to detect |
| `/nvidia` | Source | Source definition (global) — WHO generates |
| `app-crash/nvidia` | Pairing | Explicit restriction — only this combo |

**Categories** define:
- `name` — display name
- `pattern` — regex or list of regexes (case-insensitive, OR'd)
- `extract` — `{display_name: EventData_XML_field}` mapping
- `source_field` — which extract field identifies the source (for dedup grouping)

**Sources** define:
- `name` — display name
- `match` — regex matched against message + EventData values

**Category groups** with unicode icons:
```yaml
categories:
  app: {icon: "\U0001F4BB"}      # app-crash, app-hang
  service: {icon: "\u2699"}      # service-crash, service-failure
  device: {icon: "\U0001F50C"}   # device-failure
  system: {icon: "\U0001F5A5"}   # system-bsod, system-dns, etc.
  windows: {icon: "\U0001FA9F"}  # windows-update, etc.
  security: {icon: "\U0001F512"} # security-kerberos, etc.
```

A `/source` without explicit pairings is **global** (matches all categories). To restrict, omit `/source` and use only `category/source` pairs.

## Stats File

**`{hostname}.yaml`** (e.g., `Alex-PC.yaml`) — auto-generated next to config:
- `host`, `generated` timestamp
- `logs` — per-log, per-severity: last_message, last_seen, count
- `common_errors` — per-category slug: count
- `common_sources` — per-source slug: count + error breakdown

Stats are loaded on startup for instant display; recalculated from events in background.

## Event Processing Pipeline

1. **Query** — `wevtutil qe` with XPath filter (level, time window), rendered XML
2. **Parse** — XML to dict: datetime, level, provider (strip `Microsoft-Windows-`), log (single letter: A/S/X/C), EventData fields
3. **Tag** — match against categories (first match wins), then attribute to source
4. **Dedup** — global dedup by key:
   - Named source: `source|{slug}` (all NVIDIA events = 1 line)
   - Category + source_value: `error|{slug}|{value}` (per-app grouping)
   - Category only: `error|{slug}` (collapse all of type)
   - Default: normalized message (numbers + GUIDs replaced)
5. **Display** — DataTable with Source column showing `icon category/source`

## TUI Layout

```
+--[ Header: title + progress subtitle ]--------------------+
|                                                            |
|  History (DataTable, 2/3 height)                           |
|  Since | Lvl | Log | Source | Provider | ID | Message | x  |
|                                                            |
+------------------------------------------------------------+
|  Common Errors (2/5 width)  |  Detail (3/5 width)         |
|  - Categories (slug + icon) |  - Event detail on select   |
|  - Sources (sorted by count)|  - Loading progress          |
|    - error breakdown        |  - Overlap analysis          |
+------------------------------------------------------------+
+--[ Footer: keybindings ]-----------------------------------+
```

## Keybindings

| Key | Action | Description |
|-----|--------|-------------|
| `q` | Quit | Exit |
| `d` | Dark/Light | Toggle theme |
| `s` | Stats | Recalculate and save stats |
| `r` | Refresh | Refresh errors display |
| `c` | Clear Logs | Clear all configured Windows event logs (needs admin) |
| `e` | Export History | Save history to timestamped `.txt` |
| `w` | Export Errors | Save errors/sources table to `.txt` |
| `a` | Add Rule | Auto-add `category/` or `/source` to `error_rules.yaml` based on selected row |
| `o` | Overlap | Analyze rules: coverage, overlaps, gaps, unused rules |
| `Esc` | Clear Detail | Reset detail panel |
| Enter | Select Row | Show full event detail + EventData XML fields |

## CLI Modes

```bash
python w11_events.py                     # TUI (default)
python w11_events.py --stats             # Recalculate stats, print summary, exit
python w11_events.py --clear-logs        # Clear all configured logs (needs admin)
python w11_events.py --days 30           # Override time window
python w11_events.py --level Error       # Override severity
python w11_events.py --all-logs          # Scan all 1200+ log channels
python w11_events.py --logs System       # Specific logs
python w11_events.py --no-dedup          # Disable dedup
python w11_events.py --export events.json # Export to JSON
```

## Overlap Analyzer (`o` key)

1. **Coverage** — % of events matched to a category
2. **Category overlap** — events matching >1 category
3. **Source overlap** — events claimed by >1 source
4. **No category** — unmatched events (candidates for new `category/`)
5. **No source** — matched category but no source (candidates for `/source`)
6. **Unused rules** — categories/sources with zero matches

## Add Rule (`a` key)

Context-aware — inspects selected history row:
- **No category match** — generates `category/` with auto-pattern from message
- **Has category, no source** — generates `/source` with slugified app/service name
- **Already matched** — reports existing match

Writes to `error_rules.yaml` via gppu `dict_to_yml`, registers live in tracker.
