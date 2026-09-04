"""Weekly limit and effort status line metrics."""

import re

import statusline.status_line as status_line
from statusline.status_line import _feffort_icon, _ftime_left, _pre_render, _render_template
from statusline.templates import LINE1, TEMPLATES


def _plain(value):
    return re.sub(r"\x1b\[[0-9;]*m", "", value)


def test_time_left_switches_to_days_only_after_50_hours(monkeypatch):
    now = 2_000_000
    monkeypatch.setattr(status_line.time, "time", lambda: now)

    assert _ftime_left(now + 49 * 3600 + 3599) == "49h"
    assert _ftime_left(now + 50 * 3600) == "50h"
    assert _ftime_left(now + 50 * 3600 + 1) == "2d"
    assert _ftime_left(now + 7 * 86400 - 1) == "6d"


def test_weekly_limit_shows_percent_left_and_time_left(monkeypatch):
    now = 2_000_000
    monkeypatch.setattr(status_line.time, "time", lambda: now)
    ctx = {
        "rate_limits": {
            "seven_day": {
                "used_percentage": 90.4,
                "resets_at": now + 52 * 3600,
            },
        },
    }

    assert _plain(_render_template(TEMPLATES["limit_7d"], ctx)) == "📅 10% 2d"


def test_effort_icons_cover_every_claude_level():
    assert {
        level: _feffort_icon(level)
        for level in ("low", "medium", "high", "xhigh", "max")
    } == {
        "low": "▁",
        "medium": "▃",
        "high": "▅",
        "xhigh": "▇",
        "max": "█",
    }


def test_effort_icon_follows_context_size():
    stats = {
        "model": {"display_name": "Opus 4.7"},
        "output_style": {"name": "default"},
        "context_window": {
            "context_window_size": 1_000_000,
            "used_percentage": None,
        },
        "effort": {"level": "xhigh"},
    }
    rendered = _pre_render(stats)

    assert _plain(_render_template(LINE1, {**stats, **rendered})) == "O 4.7·1M▇"
