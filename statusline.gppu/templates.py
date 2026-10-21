"""Status line templates: one built-in set, no external YAML to sync across installs.

Jinja templates with pre-rendered widget values.
Filters: c(color,prefix,suffix) sep(char,color) tok ms ago pct
Colors: TColor names (DC DY BG DR DM DB DIM GRAY2 …)
"""

CONTEXT_BAR_WIDTH = 60
GIT_TTL = 10
JSONL_TTL = 2
OV_TTL = 5

# Each element carries its own color so it is identifiable without reading it.
# Colors that ramp (context badge, weekly limit, +/- lines, OV health) mean state;
# every other color is just that element's identity.
LINE1 = "{{ model }}{{ effort_icon }} {{ context_pct }}{{ limit_7d|sep }}{{ user_turns|c('DC','🐯 ')|sep }} {{ assistant_msgs|c('BP','🤖 ') }}{{ top_tools|sep }}{{ started_ago|c('DGOLD','🕐 ')|sep }}{{ wall_time|c('BO','⏱️ ')|sep }}{{ api_time|c('DPINK','⚙️ ')|sep }}"
LINE2 = "{{ project|c('BGOLD') }} {{ project_folder|c('GRAY4','📂 ') }}{{ hostname|c('DM','💻 ')|sep }}{{ git_remote|c('DB')|sep }}{{ git_branch|sep }}{{ lines_changed|sep }}{{ ov_score|sep }}{{ ov_recall|sep }}{{ ov_state|sep }}{{ ov_capture|sep }}"
LINE2_INDENT = "  "

# Model carries its own colors: the model itself reads brighter than the
# style/window suffix trailing it, so the slash separates two weights.
_MODEL = """
{% set name = (model.display_name | default('')).split('(')[0] | trim -%}
{% set lo = name | lower -%}
{% if 'opus' in lo -%}
  {% set short = 'O ' ~ name.split()[-1] -%}
{% elif 'sonnet' in lo -%}
  {% set short = 's ' ~ name.split()[-1] -%}
{% elif 'haiku' in lo -%}
  {% set short = 'h ' ~ name.split()[-1] -%}
{% else -%}
  {% set short = name -%}
{% endif -%}
{{ short | c('DW') -}}
{% if output_style is mapping and output_style.name and output_style.name != 'default' -%}
  {{ ('/' ~ (output_style.name[0] | upper)) | c('GRAY1') -}}
{% endif -%}
{% if context_window is mapping and context_window.context_window_size -%}
  {% if context_window.context_window_size >= 1000000 -%}
    {{ ('·' ~ (context_window.context_window_size // 1000000) ~ 'M') | c('GRAY1') -}}
  {%- else -%}
    {{ ('·' ~ (context_window.context_window_size // 1000) ~ 'k') | c('GRAY1') -}}
  {%- endif -%}
{% endif %}
"""

# Context reads as a filled badge (black on color) rather than a bare number:
# the block of color is what catches the eye, the digits confirm it. Headroom
# left is what the gradient tracks, so the badge greens down as it fills.
_CONTEXT_PCT = """
{% if context_window is mapping and context_window.used_percentage is not none -%}
  {% set p = context_window.used_percentage | int -%}
  {{ (' ' ~ p ~ '% ') | grad(100 - p, 0, 100, true) }}
{%- endif %}
"""

_LIMIT_5H = """
{% if rate_limits.five_hour.used_percentage is number -%}
  {% set left = (100 - rate_limits.five_hour.used_percentage) | round | int -%}
  {{ ('5h ' ~ left ~ '%') | c('DG' if left >= 50 else 'DY' if left >= 20 else 'DR') }}
{%- endif %}
"""

# Weekly headroom and time until reset. Abundant headroom stays quiet; urgency
# brightens toward 20%, then turns red.
_LIMIT_7D = """
{% if rate_limits.seven_day.used_percentage is number -%}
  {% set left = (100 - rate_limits.seven_day.used_percentage) | round | int -%}
  {% set reset = rate_limits.seven_day.resets_at | time_left -%}
  {% set text = '📅 ' ~ left ~ '%' -%}
  {% if reset -%}{% set text = text ~ ' ' ~ reset -%}{% endif -%}
  {{ text | remaining(left) }}
{%- endif %}
"""

_EFFORT = """
{% if thinking is mapping and thinking.enabled is sameas false -%}
  {{ 'disabled' | effort_icon }}
{%- elif effort is mapping and effort.level -%}
  {{ effort.level | effort_icon }}
{%- endif %}
"""

# Server reachability. The bolt carries the state as a gradient over the probe
# round-trip; the millisecond figure itself stays neutral.
_OV_STATE = """
{% if ov.health == 'ok' -%}
  {{ '⚡' | grad(1000 - ov.latency_ms, 0, 1000) }}{{ (' ' ~ ov.latency_ms ~ 'ms') | c('GRAY3') }}
{%- elif ov.health == 'slow' -%}
  {{ '⚡' | grad(0, 0, 1000) }}{{ ' >1s' | c('GRAY3') }}
{%- elif ov.health -%}
  {{ '⚡' | c('BR') }}{{ ' ✗' | c('GRAY3') }}
{%- endif %}
"""

_OV_RECALL = """
{% if ov.recall -%}
  {% if ov.recall.reason == 'ok' -%}
    {{ ('↩ ' ~ ov.recall.count) | c('DC') }}
  {%- elif ov.recall.reason == 'offline' -%}
    {{ '↩ ✗' | c('DR') }}
  {%- else -%}
    {{ '↩ 0' | c('GRAY2') }}
  {%- endif %}
{%- endif %}
"""

# Top similarity among the memories the last recall injected. Its own segment so
# the number reads at a glance; the ramp says how good the match was.
_OV_SCORE = """
{% if ov.recall and ov.recall.top_score -%}
  {% set s = ov.recall.top_score -%}
  {{ '🧠' | c('BC') }}{{ (' ' ~ ('%.2f' | format(s))[1:]) | grad(s) }}
{%- endif %}
"""

_OV_CAPTURE = """
{% if ov.capture -%}
  {% if ov.capture.turns_failed -%}
    {{ ('✎ ✗' ~ ov.capture.turns_failed) | c('DR') }}
  {%- elif ov.capture.committed -%}
    {{ '✎ ✓' | c('DG') }}
  {%- elif ov.capture.pending_tokens and ov.capture.commit_threshold -%}
    {% set fill = 100 * ov.capture.pending_tokens // ov.capture.commit_threshold -%}
    {{ ('✎ ' ~ fill ~ '%') | grad(100 - fill, 0, 100) }}
  {%- endif %}
  {%- if ov.capture.commit_count %}{{ (' ·' ~ ov.capture.commit_count) | c('GRAY2') }}{% endif -%}
{%- endif %}
"""

_GIT_REMOTE = """
{% if git.remotes | length > 1 -%}
  {% for n, u in git.remotes -%}
    {{ n }}:{{ u }}{{ ' ' if not loop.last -}}
  {% endfor -%}
{% elif git.remotes | length == 1 -%}
  {{ git.remotes[0][1] -}}
{% else -%}
  {{ git.repo_name -}}
{% endif %}
"""

_TOKEN_SPEED = """
{% if cost is mapping and cost.total_api_duration_ms
   and context_window is mapping and context_window.total_output_tokens -%}
  {{ (context_window.total_output_tokens / (cost.total_api_duration_ms / 1000)) | round | int -}}
{% endif %}
"""

_API_EFFICIENCY = """
{% if cost is mapping and cost.total_duration_ms
   and cost.total_api_duration_ms -%}
  {{ (100 * cost.total_api_duration_ms / cost.total_duration_ms) | round | int -}}
{% endif %}
"""

TEMPLATES = {
    "model": _MODEL,
    "effort_icon": _EFFORT,
    "context_pct": _CONTEXT_PCT,
    "limit_5h": _LIMIT_5H,
    "limit_7d": _LIMIT_7D,
    "ov_state": _OV_STATE,
    "ov_recall": _OV_RECALL,
    "ov_score": _OV_SCORE,
    "ov_capture": _OV_CAPTURE,
    "tool_calls": "{{ tools | counter_sum }}",
    "top_tools": "{{ tools | top_tools(5) }}",
    "user_turns": "{{ counts.user | nonzero }}",
    "assistant_msgs": "{{ counts.assistant | nonzero }}",
    "project": "{{ project_name }}",
    "project_folder": "{{ project_folder | default('') }}",
    "hostname": "{{ hostname | default('') }}",
    "started_ago": "{{ tmeta.first_ts | ago }}",
    "api_time": "{{ (cost.total_api_duration_ms | ms) if cost is mapping else '' }}",
    "wall_time": "{{ (cost.total_duration_ms | ms) if cost is mapping else '' }}",
    "tokens_in": "{{ (context_window.total_input_tokens | tok) if context_window is mapping else '' }}",
    "tokens_out": "{{ (context_window.total_output_tokens | tok) if context_window is mapping else '' }}",
    "version": "{{ tmeta.version or version | default('') }}",
    "session_name": "{{ session_name | default('') }}",
    "errors": "{{ counts.errors | nonzero }}",
    "compactions": "{{ counts.compactions | nonzero }}",
    "subagents": "{{ subagents | nonzero }}",
    "git_remote": _GIT_REMOTE,
    "token_speed": _TOKEN_SPEED,
    "api_efficiency": _API_EFFICIENCY,
}
