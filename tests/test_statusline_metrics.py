"""Weekly limit and effort status line metrics."""

import re

import statusline.status_line as status_line
from statusline.status_line import (
    _feffort_icon,
    _fremaining,
    _ftime_left,
    _pre_render,
    _render_template,
)
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


def test_weekly_remaining_brightens_then_turns_red():
    quiet = _fremaining("📅 80% 3d", 80)
    middle = _fremaining("📅 50% 2d", 50)
    near = _fremaining("📅 21% 1d", 21)
    danger = _fremaining("📅 20% 1d", 20)

    assert "\x1b[38;5;240m" in quiet
    assert "\x1b[38;5;247m" in middle
    assert "\x1b[38;5;255m" in near
    assert "\x1b[48;5;196;38;5;15;1m" in danger
    assert _plain(quiet) == "📅 80% 3d"
    assert _plain(danger) == "📅 20% 1d"


def test_effort_icons_cover_every_supported_state():
    icons = {
        level: _feffort_icon(level)
        for level in ("disabled", "low", "medium", "high", "xhigh", "max", "ultra")
    }

    assert {level: _plain(icon) for level, icon in icons.items()} == {
        "disabled": "⊘",
        "low": "·",
        "medium": "○",
        "high": "◔",
        "xhigh": "●",
        "max": "●",
        "ultra": "●",
    }
    assert "\x1b[38;5;37m" in icons["xhigh"]
    assert "\x1b[38;5;201m" in icons["ultra"]
    assert "\x1b[" not in icons["max"]


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

    assert _plain(_render_template(LINE1, {**stats, **rendered})) == "O 4.7·1M●"


def test_disabled_thinking_takes_precedence_over_effort():
    stats = {
        "model": {"display_name": "Opus 4.7"},
        "output_style": {"name": "default"},
        "context_window": {
            "context_window_size": 1_000_000,
            "used_percentage": None,
        },
        "effort": {"level": "ultra"},
        "thinking": {"enabled": False},
    }
    rendered = _pre_render(stats)

    assert _plain(_render_template(LINE1, {**stats, **rendered})) == "O 4.7·1M⊘"
