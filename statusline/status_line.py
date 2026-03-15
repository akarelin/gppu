#!/usr/bin/env python3
"""Claude Code 2-line status line.

Uses gppu for config and colors, Jinja for widget templates, cache.py for incremental parsing.

build_stats() → {**stdin_data, enrichments} — raw merged dicts
line1/line2: Jinja templates with pre-rendered widget values.
Filters: c(color,prefix,suffix) seg(sep,sep_color) tok ms ago pct counter_sum top_tools nonzero
"""

import json
import os
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from collections import Counter
from pathlib import Path

from gppu import Env, TColor
from gppu.gppu import _colorize
from jinja2 import Environment, Undefined

from statusline.cache import transcript_stats_cached, git_info_cached, init_cache
from statusline.stats import git_info

# ── Config discovery ──────────────────────────────────────────────────────

def _config_dir() -> Path:
    """Resolve config directory for statusline YAML files.

    Priority: STATUSLINE_CONFIG_DIR env var > ~/.config/statusline > APPDATA/statusline.
    """
    override = os.environ.get("STATUSLINE_CONFIG_DIR")
    if override:
        return Path(override)
    # Prefer ~/.config/statusline on all platforms (chezmoi default)
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "statusline"
    if xdg.is_dir():
        return xdg
    # Windows fallback: %APPDATA%/statusline
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "statusline"
        if appdata.is_dir():
            return appdata
    return xdg

# ── Initialize gppu ────────────────────────────────────────────────────────

Env(name="status_line", app_path=_config_dir())
Env.load()
glob = Env.glob
glob_dict = Env.glob_dict
glob_int = Env.glob_int
glob_list = Env.glob_list

# ── Jinja filters ──────────────────────────────────────────────────────────

def _ftok(n):
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _fms(ms):
    if not ms or ms <= 0:
        return ""
    s = ms // 1000
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}:{s:02d}"
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _fago(val):
    if not val:
        return ""
    if isinstance(val, str):
        from datetime import datetime, timezone
        try:
            ts = val.rstrip("Z").split(".")[0]
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            seconds = time.time() - dt.timestamp()
        except Exception:
            return ""
    else:
        seconds = val
    s = int(seconds)
    if s < 60:
        return f"{s}s ago"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h{m:02d}m ago" if m else f"{h}h ago"
    d, h = divmod(h, 24)
    return f"{d}d{h}h ago" if h else f"{d}d ago"


def _fpct(val):
    if val is None:
        return ""
    return str(int(float(val)))


def _fcounter_sum(val):
    if not val:
        return ""
    return str(sum(val.values()))


def _ftop_tools(tools, n=6):
    if not tools:
        return ""
    if isinstance(tools, Counter):
        return " ".join(f"{name}({c})" for name, c in tools.most_common(n))
    return ""


def _fnonzero(val):
    return str(val) if val else ""


def _fc(val, color, prefix='', suffix=''):
    """Colorize val with TColor name. Returns '' if val is empty."""
    if not val:
        return ''
    text = f"{prefix}{val}{suffix}"
    tc = getattr(TColor, color, None)
    return _colorize(text, tc) if tc else text


def _fsep(val, sep='|', color='GRAY2'):
    """Prepend colored separator if val is non-empty."""
    if not val:
        return ''
    tc = getattr(TColor, color, None)
    s = f" {_colorize(sep, tc)} " if tc else f" {sep} "
    return s + str(val)


class _SilentUndefined(Undefined):
    """Undefined that returns empty/falsy instead of raising."""
    def __str__(self):
        return ""
    def __bool__(self):
        return False
    def __iter__(self):
        return iter([])
    def __getattr__(self, name):
        return self
    def __getitem__(self, name):
        return self

_JINJA_ENV = Environment(undefined=_SilentUndefined)
_JINJA_ENV.filters["tok"] = _ftok
_JINJA_ENV.filters["ms"] = _fms
_JINJA_ENV.filters["ago"] = _fago
_JINJA_ENV.filters["pct"] = _fpct
_JINJA_ENV.filters["counter_sum"] = _fcounter_sum
_JINJA_ENV.filters["top_tools"] = _ftop_tools
_JINJA_ENV.filters["nonzero"] = _fnonzero
_JINJA_ENV.filters["c"] = _fc
_JINJA_ENV.filters["sep"] = _fsep

_template_cache = {}


def _render_template(template_str, ctx):
    tmpl = _template_cache.get(template_str)
    if tmpl is None:
        tmpl = _JINJA_ENV.from_string(template_str)
        _template_cache[template_str] = tmpl
    return tmpl.render(ctx).strip()


# ── Raw stats builder ───────────────────────────────────────────────────────

def build_stats(data):
    """Merge raw stdin data with enrichments. No extraction, no calculations."""
    ws = data.get("workspace", {})
    cwd = ws.get("current_dir") or data.get("cwd", "")
    transcript_path = data.get("transcript_path", "")
    project_dir = ws.get("project_dir") or cwd

    gi = git_info_cached(cwd, git_info)
    tools, counts, tmeta, subagent_count = transcript_stats_cached(transcript_path)

    return {
        **data,
        "tools": tools,
        "counts": counts,
        "tmeta": tmeta,
        "subagents": subagent_count,
        "git": gi,
        "project_dir": project_dir,
        "project_name": os.path.basename(project_dir) if project_dir else "",
    }


# ── Complex formatters (internal ANSI via gppu) ─────────────────────────────

def _fmt_context_bar(s):
    ctx = s.get("context_window") or {}
    pct_raw = ctx.get("used_percentage")
    if pct_raw is None:
        return ""
    pct = int(float(pct_raw))
    width = glob_int("context_bar_width", 60)
    window = ctx.get("context_window_size") or 200_000
    usage = ctx.get("current_usage") or {}
    cache_r = usage.get("cache_read_input_tokens", 0)
    cache_w = usage.get("cache_creation_input_tokens", 0)
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    used = cache_r + cache_w + inp + out
    tokens_in = ctx.get("total_input_tokens", 0)
    tokens_out = ctx.get("total_output_tokens", 0)
    tools_tok = max(0, used - tokens_in - tokens_out)
    free = max(0, window - used)
    total = tools_tok + tokens_in + tokens_out + free or 1
    def cells(t): return max(0, round(width * t / total))
    c_tools = cells(tools_tok)
    c_in = cells(tokens_in)
    c_out = cells(tokens_out)
    c_free = width - c_tools - c_in - c_out
    if c_free < 0:
        c_tools = max(0, c_tools + c_free)
        c_free = 0
    pct_color = TColor.DG if pct < 50 else TColor.DY if pct < 80 else TColor.DR
    segs = []
    if c_tools: segs.append(_colorize("█" * c_tools, TColor.DC))
    if c_in:    segs.append(_colorize("█" * c_in, TColor.DM))
    if c_out:   segs.append(_colorize("█" * c_out, TColor.BY))
    dim_sep = _colorize("│", TColor.DIM)
    filled = dim_sep.join(segs)
    if c_free:
        free_block = _colorize("░" * c_free, TColor.DIM)
        filled += (dim_sep + free_block) if segs else free_block
    return f"{filled} {_colorize(f'{pct}%', pct_color)}"


def _fmt_git_branch(s):
    gi = s.get("git", {})
    if not gi.get("branch"):
        return ""
    markers = []
    if gi["dirty"]:  markers.append(_colorize("*", TColor.DR))
    if gi["ahead"]:  markers.append(_colorize(f"↑{gi['ahead']}", TColor.BG))
    if gi["behind"]: markers.append(_colorize(f"↓{gi['behind']}", TColor.DR))
    if gi["stash"]:  markers.append(_colorize(f"≡{gi['stash']}", TColor.DM))
    branch = _colorize(gi["branch"], TColor.DY)
    return branch + (" " + "".join(markers) if markers else "")


def _fmt_lines_changed(s):
    cost = s.get("cost") or {}
    a = cost.get("total_lines_added", 0)
    r = cost.get("total_lines_removed", 0)
    if not a and not r:
        return ""
    return f"{_colorize(f'+{a}', TColor.BG)}{_colorize('/', TColor.DIM)}{_colorize(f'-{r}', TColor.DR)}"


def _fmt_cache_tokens(s):
    usage = (s.get("context_window") or {}).get("current_usage") or {}
    cr = usage.get("cache_read_input_tokens", 0)
    cw = usage.get("cache_creation_input_tokens", 0)
    if not cr and not cw:
        return ""
    parts = []
    if cr: parts.append(_colorize(f"r:{_ftok(cr)}", TColor.DC))
    if cw: parts.append(_colorize(f"w:{_ftok(cw)}", TColor.DM))
    return _colorize("/", TColor.DIM).join(parts)


_FORMATTERS = {
    "context_bar":     _fmt_context_bar,
    "git_branch":      _fmt_git_branch,
    "lines_changed":   _fmt_lines_changed,
    "cache_tokens":    _fmt_cache_tokens,
}


# ── Rendering ───────────────────────────────────────────────────────────────

def _pre_render(stats):
    """Pre-render all widget templates and formatters into string values."""
    templates = glob_dict("templates")
    ctx = {**stats, "cfg": Env.data}
    rendered = {}
    for name, tmpl_str in templates.items():
        rendered[name] = _render_template(tmpl_str, ctx)
    for name, func in _FORMATTERS.items():
        rendered[name] = func(stats)
    return rendered


def main():
    data = json.loads(sys.stdin.read())
    init_cache(Env.data)
    stats = build_stats(data)
    rendered = _pre_render(stats)
    ctx = {**stats, **rendered, "cfg": Env.data}

    line1_tmpl = glob("line1")
    line2_tmpl = glob("line2")
    indent = glob("line2_indent") or "  "

    if line1_tmpl:
        line1 = _render_template(line1_tmpl, ctx)
        if line1:
            print(line1)
    if line2_tmpl:
        line2 = _render_template(line2_tmpl, ctx)
        if line2:
            print(f"{indent}{line2}")


if __name__ == "__main__":
    main()
