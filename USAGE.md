# gppu Usage Across Projects

## Overview

gppu (General Purpose Python Utilities) is used across three main projects: **Y2** (AppDaemon automation), **CRAP** (data pipelines & ETLs), and **RAN** (infrastructure scripts).

## Y2 (AppDaemon / ad_unibridge)

Y2 is the heaviest consumer. It uses nearly every gppu feature.

| Module | Imports |
|--------|---------|
| `y2env.py` | `VER_GPPU`, `TRACE_RULES`, `Logger`, `init_logger`, `Error`, `dict_from_yml`, `deepget`, `deepget_dict`, `deepget_int`, `deepget_list`, `dict_all_paths`, `safe_int`, `dict_sanitize`, `y2eid` |
| `y2util.py` | `safe_int`, `safe_float`, `safe_timedelta`, `dict_to_yml`, `dict_sanitize`, `dpcp`, `now_ts`, `DC`, `_mixin`, `mixin_Logger`, `y2eid`, `y2topic`, `Logger`, `Warn` |
| `y2api.py` | `y2eid`, `y2topic`, `safe_int`, `safe_float`, `safe_timedelta`, `dict_sanitize`, `dict_to_yml`, `dict_all_paths`, `dpcp`, `now_ts`, `DC`, `mixin_Logger`, `_mixin`, `mixin_Config`, `deepget`, `deepget_int`, `deepget_dict`, `deepget_list` |
| `y2objects.py` | `dict_template_populate`, `now_ts`, `y2eid`, `safe_float`, `safe_int` |
| `Y2_services.py` | `Env`, `safe_int`, `y2topic`, `y2eid` |
| `Y2_insteon.py` | `dict_template_populate`, `now_ts`, `safe_int`, `y2eid`, `DC`, `mixin_Logger` |
| `Y2_insteon_compiler.py` | `dict_to_yml`, `dict_template_populate` |

## CRAP (Data Pipelines)

CRAP primarily uses `Env` for configuration and the database base classes.

### Airflow DAGs
All DAGs follow the same pattern - import `Env` for configuration:
- `ticktick/`, `telegram/`, `slack/`, `imessage/`, `confluence/`, `msgraph/`, `photos/`, `activity/`, `google/`

### Standalone Tools
| Project | Imports |
|---------|---------|
| `preservator/preserve_all.py` | `Env`, `Info`, `Warn`, `Error`, `Debug`, `dict_from_yml`, `detect_os` |
| `openkm_indexer/` | `_PGBase`, `_Base`, `Env`, `init_logger` |
| `file_indexer/` | `_Base`, `_PGBase`, `Env`, `OSType`, `detect_os`, `init_logger`, `Error`, `dict_from_yml` |
| `photo_indexer/` | `_Base`, `Env`, `dict_from_yml`, `deepget`, `deepget_list`, `Error`, `Info`, `detect_os`, `OSType` |
| `CRM.dumper/` | `Env` |
| `CRM.ajacent/Outlookery/` | `dict_from_yml`, `dict_to_yml` |
| `ETLs/iMessage.2025/` | `dict_from_yml`, `deepget`, `Env` |
| `ETLs/Xsolla-email2email/` | `safe_int`, `safe_float` |
| `ETLs/Autome/IoT/` | `dict_from_yml`, `pcp` |
| `ETLs/Telegram/` | `append_timestamp` |
| `ETLs/ticktick/` | `append_timestamp` |
| `ETLs/Slack2Obsidian/` | `Env` |

## RAN (Infrastructure)

| Script | Imports |
|--------|---------|
| `Scripting/statusline/status_line.py` | `Env`, `TColor`, `_colorize`, `glob`, `glob_dict`, `glob_int`, `glob_list` |

## Most Used Functions (by import count)

1. **`Env`** - 30+ imports (universal config loader)
2. **`deepget` / `deepget_*`** - 10+ imports (nested dict access)
3. **`safe_int` / `safe_float`** - 8+ imports (type coercion)
4. **`dict_from_yml`** - 7+ imports (YAML loading with !include)
5. **`y2eid`** - 6+ imports (entity ID handling, Y2-specific)
6. **`dict_to_yml` / `dict_sanitize`** - 5+ imports (YAML output)
7. **`Logger` / `Info` / `Error` / `Warn`** - 5+ imports (colored logging)
8. **`DC`** - 3+ imports (pseudo-dataclass)
9. **`dict_template_populate`** - 3+ imports (template expansion)
10. **`_Base` / `_PGBase`** - 3+ imports (OOP base classes)
