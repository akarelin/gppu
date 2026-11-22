"""Progress for long-running TUI and CLI operations, and the markers a strip of items is drawn with.

- :class:`TickProgress` writes a dim ``·`` per item, a strip every N items or T seconds, whichever comes first, and a closing
  count. It writes through the caller's ``log``, in Rich markup (``rich=True``, for a Textual RichLog) or raw ANSI.
- :class:`Marker` is a category with its glyph and colours; :func:`legend_ansi` writes the key of a set of them
  (``examples/sessions_clean.py``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .icons import marker_ansi


# .. ── marker type ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Marker:
    """A classification bucket with visual identity: any category with a coloured glyph; the type carries no domain knowledge."""
    key: str                          # .. 'claude', 'hot', 'db1' — sort/group key
    label: str                        # .. 'Claude', 'Hot zone' — human label
    symbol: str                       # .. '✻', '●' — one glyph
    rich_color: str                   # .. 'bright_cyan' — Rich / Textual markup name
    ansi_code: str                    # .. '38;5;14' — SGR params for plain ANSI


def legend_ansi(markers: tuple[Marker, ...]) -> str:
    return '  '.join(f'{marker_ansi(m)}={m.label}' for m in markers)


# .. ── streaming tracker ──────────────────────────────────────────────────────

class TickProgress:
    """Dim ``·`` per item, no classification.

    When ``close()`` runs with zero items noted, no output is emitted —
    callers don't have to branch on "did the source find anything".
    """

    def __init__(self, log: Callable[[str], None], *,
                 rich: bool = True,
                 tick_every: int = 100,
                 tick_seconds: float = 2.0):
        self._log = log
        self._tick_every = max(1, tick_every)
        self._tick_seconds = tick_seconds
        self._last_flush = 0.0
        self._rich = rich
        self._pending = 0
        self._total = 0

    def note(self) -> None:
        self._pending += 1
        self._total += 1
        if self._pending >= self._tick_every or time.time() - self._last_flush >= self._tick_seconds:
            self._flush()

    def _tick(self) -> str:
        return '[dim]·[/]' if self._rich else '\x1b[38;5;8m·\x1b[0m'

    def _flush(self) -> None:
        if not self._pending:
            return
        self._log(f'    {self._tick() * self._pending}  ({self._total})')
        self._pending = 0
        self._last_flush = time.time()

    def close(self) -> None:
        if self._total == 0:
            return
        self._flush()
        self._log(f'    discovered {self._total} items')
