"""GitHub-style activity heatmap for daily counts.

Renders a 7-row × N-column grid (one cell per day, grouped into weeks) with
Unicode density blocks ``·`` < ``░`` < ``▒`` < ``▓`` < ``█`` and a per-day
color scale from dim through green/yellow/orange to red.  Input is simply a
``dict[date, int]`` — the caller is responsible for aggregating whatever
counts matter (sessions, commits, events …).

Two entry points:

- :func:`render_heatmap_lines` — pure function returning a list of Rich-
  markup strings.  Useful for writing into an existing ``RichLog`` / plain
  ``Console``.
- :class:`Heatmap` — Textual widget that wraps the same output in a
  ``Static`` so it composes into any layout.

Design is faithful to SessionManager's original
(``scripts/sm-tui.py:840-909``) — same thresholds, same weekday-label
layout, same totals line.  Extracted here so preservator and future
CRAP apps can reuse without copy-paste.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

try:
    from textual.app import ComposeResult
    from textual.widgets import Static
    _TEXTUAL = True
except ImportError:
    _TEXTUAL = False


_BLOCK_THRESHOLDS = (
    # (upper-bound-inclusive, block, color)
    (0,    '·', 'bright_black'),
    (2,    '░', 'green'),
    (8,    '▒', 'yellow'),
    (24,   '▓', 'orange3'),
    (None, '█', 'red'),            # None = unbounded
)

_WEEKDAY_LABELS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


def _cell(n: int) -> tuple[str, str]:
    """Return (glyph, color) for count ``n``."""
    for bound, glyph, color in _BLOCK_THRESHOLDS:
        if bound is None or n <= bound:
            return glyph, color
    return _BLOCK_THRESHOLDS[-1][1], _BLOCK_THRESHOLDS[-1][2]


def render_heatmap_lines(
    counts: dict[date, int],
    *,
    days: int = 90,
    title: str | None = 'Activity heatmap',
    unit: str = 'session-days',
) -> list[str]:
    """Render a heatmap as a list of Rich-markup lines.

    ``counts`` need only contain the days that had activity; missing days
    are treated as zero.  The grid always covers the trailing ``days``
    ending today.
    """
    today = datetime.now().date()
    span = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]

    # Pad so the earliest day lands on a Monday → GitHub-style columns align.
    pad = span[0].weekday()                       # 0 = Monday
    padded: list[date | None] = [None] * pad + list(span)
    weeks = [padded[i:i + 7] for i in range(0, len(padded), 7)]

    lines: list[str] = []
    if title:
        lines.append(f'[bold]{title} — last {days} days[/]')
        lines.append('(each cell = 1 day; ░ ▒ ▓ █ by count; ·=0)')
        lines.append('')

    for wd in range(7):
        cells = []
        for week in weeks:
            if wd >= len(week) or week[wd] is None:
                cells.append(' ')
            else:
                n = counts.get(week[wd], 0)
                glyph, color = _cell(n)
                cells.append(f'[{color}]{glyph}[/]')
        lines.append(f'  {_WEEKDAY_LABELS[wd]:<4}' + ''.join(cells))

    total = sum(counts.get(d, 0) for d in span)
    active = sum(1 for d in span if counts.get(d, 0) > 0)
    lines.append('')
    lines.append(f'total activity: {total} {unit}  ·  active days: {active}/{days}')
    return lines


def counts_from_timestamps(timestamps: Iterable[datetime | str]) -> dict[date, int]:
    """Helper — fold an iterable of timestamps into a per-day count dict.

    ``str`` inputs are parsed as ISO-8601 (trailing ``Z`` treated as UTC).
    Unparseable entries are skipped silently; for stricter handling the
    caller can build the dict directly.
    """
    out: dict[date, int] = {}
    for t in timestamps:
        if isinstance(t, str):
            try:
                t = datetime.fromisoformat(t.replace('Z', '+00:00'))
            except ValueError:
                continue
        if not isinstance(t, datetime):
            continue
        d = t.date()
        out[d] = out.get(d, 0) + 1
    return out


# ── Textual widget wrapper ────────────────────────────────────────────────

if _TEXTUAL:

    class Heatmap(Static):
        """Textual widget that renders :func:`render_heatmap_lines` output.

        Update via :meth:`set_counts` to re-render in place.
        """

        DEFAULT_CSS = """
        Heatmap {
            height: auto;
            padding: 0 1;
        }
        """

        def __init__(self, counts: dict[date, int] | None = None, *,
                     days: int = 90,
                     title: str | None = 'Activity heatmap',
                     unit: str = 'session-days',
                     **kwargs):
            super().__init__('', markup=True, **kwargs)
            self._days = days
            self._title = title
            self._unit = unit
            self.set_counts(counts or {})

        def set_counts(self, counts: dict[date, int]) -> None:
            lines = render_heatmap_lines(counts, days=self._days,
                                         title=self._title, unit=self._unit)
            self.update('\n'.join(lines))

else:
    Heatmap = None  # type: ignore[assignment]
