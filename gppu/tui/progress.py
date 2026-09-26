"""Streaming progress indicators for long-running TUI / CLI operations.

Two flavors, both sharing the same batching/flushing design: emit a strip
of markers every N items or every T seconds, whichever fires first.  A
final summary line closes the strip.

Consumers supply a ``log: Callable[[str], None]`` — usually the app's main
log writer (Textual RichLog, plain ``print``, or anything that takes one
string per line).  Markup mode is controlled by a ``rich`` flag:

- ``rich=True`` (default): emits Rich markup — ``[color]glyph[/]`` — for
  Textual RichLog with ``markup=True``.
- ``rich=False``: emits raw ANSI escapes, suitable for plain CLI output on
  a TTY.  A caller routing through ``rich.Console.print`` can keep
  ``rich=True`` and let Console convert markup to ANSI on non-TTY it will
  strip markup automatically.

Two classes:

- :class:`TickProgress` — dim ``·`` per item, no classification.  For
  generic per-item discovery where category is irrelevant.
- :class:`MarkerProgress` — one colored glyph per item, classified by a
  caller-supplied classifier.  Used for preservator's LLM-session source
  (marker = Claude/Codex/Gemini/…) but fully generic — the classifier is
  an injected callable plus a ``Marker`` tuple, no LLM knowledge in gppu.

Example — using MarkerProgress for anything category-typed::

    from gppu.tui.progress import Marker, MarkerProgress

    CATEGORIES = (
        Marker('hot',  'Hot',  '●', 'bright_red',    '38;5;9'),
        Marker('warm', 'Warm', '◉', 'bright_yellow', '38;5;11'),
        Marker('cold', 'Cold', '○', 'bright_blue',   '38;5;12'),
    )
    UNKNOWN = Marker('other', 'other', '·', 'dim white', '38;5;8')

    def classify(temp: float) -> Marker:
        if temp > 70:  return CATEGORIES[0]
        if temp > 40:  return CATEGORIES[1]
        return CATEGORIES[2]

    prog = MarkerProgress(log, CATEGORIES, UNKNOWN, classify)
    for t in temps:
        prog.note(t)
    prog.close()
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


T = TypeVar('T')


@dataclass(frozen=True)
class Marker:
    """A classification bucket with visual identity.

    Used by :class:`MarkerProgress`.  Any category enum with a colored
    glyph works — preservator uses it for LLM vendors, but the type
    itself carries no domain knowledge.
    """
    key: str                          # 'claude', 'hot', 'db1' — sort/group key
    label: str                        # 'Claude', 'Hot zone' — human label
    symbol: str                       # '✻', '●' — one glyph
    rich_color: str                   # 'bright_cyan' — Rich / Textual markup name
    ansi_code: str                    # '38;5;14' — SGR params for plain ANSI


def marker_rich(marker: Marker) -> str:
    """Rich-markup symbol — ``[bright_cyan]✻[/]``."""
    return f'[{marker.rich_color}]{marker.symbol}[/]'


def marker_ansi(marker: Marker) -> str:
    """Raw ANSI-escaped symbol — used when writing to a plain terminal."""
    return f'\x1b[{marker.ansi_code}m{marker.symbol}\x1b[0m'


def legend_rich(markers: tuple[Marker, ...]) -> str:
    """One-line key — ``✻=Claude  ▲=Codex  ...`` in Rich markup."""
    return '  '.join(f'{marker_rich(m)}={m.label}' for m in markers)


def legend_ansi(markers: tuple[Marker, ...]) -> str:
    return '  '.join(f'{marker_ansi(m)}={m.label}' for m in markers)


# ── streaming trackers ─────────────────────────────────────────────────────

class _BatchedStrip:
    """Internal helper — batches strip emission by count or elapsed time."""

    def __init__(self, log: Callable[[str], None], *,
                 tick_every: int, tick_seconds: float):
        self._log = log
        self._tick_every = max(1, tick_every)
        self._tick_seconds = tick_seconds
        self._last_flush = 0.0

    def _time_to_flush(self, pending: int) -> bool:
        return (pending >= self._tick_every
                or time.time() - self._last_flush >= self._tick_seconds)

    def _stamp(self) -> None:
        self._last_flush = time.time()


class TickProgress(_BatchedStrip):
    """Dim ``·`` per item, no classification.

    When ``close()`` runs with zero items noted, no output is emitted —
    callers don't have to branch on "did the source find anything".
    """

    def __init__(self, log: Callable[[str], None], *,
                 rich: bool = True,
                 tick_every: int = 100,
                 tick_seconds: float = 2.0):
        super().__init__(log, tick_every=tick_every, tick_seconds=tick_seconds)
        self._rich = rich
        self._pending = 0
        self._total = 0

    def note(self) -> None:
        self._pending += 1
        self._total += 1
        if self._time_to_flush(self._pending):
            self._flush()

    def _tick(self) -> str:
        return '[dim]·[/]' if self._rich else '\x1b[38;5;8m·\x1b[0m'

    def _flush(self) -> None:
        if not self._pending:
            return
        self._log(f'    {self._tick() * self._pending}  ({self._total})')
        self._pending = 0
        self._stamp()

    def close(self) -> None:
        if self._total == 0:
            return
        self._flush()
        self._log(f'    discovered {self._total} items')


class MarkerProgress(_BatchedStrip, Generic[T]):
    """One colored glyph per item, classified by a caller-supplied function.

    ``classify`` takes whatever :meth:`note` gets passed (a path, a record,
    anything) and returns a :class:`Marker` — usually drawn from
    ``categories`` but may return ``unknown`` for items that fall through.

    Per-category counts are tracked and surfaced via :meth:`summary`; the
    closing line lists them in category order.
    """

    def __init__(self, log: Callable[[str], None],
                 categories: tuple[Marker, ...],
                 unknown: Marker,
                 classify: Callable[[T], Marker],
                 *,
                 rich: bool = True,
                 tick_every: int = 50,
                 tick_seconds: float = 2.0,
                 noun: str = 'items'):
        """
        ``noun`` is used in :meth:`summary` — e.g. ``'sessions'``,
        ``'records'``.  Default ``'items'``.
        """
        super().__init__(log, tick_every=tick_every, tick_seconds=tick_seconds)
        self._rich = rich
        self._categories = categories
        self._unknown = unknown
        self._classify = classify
        self._noun = noun
        self._pending: list[Marker] = []
        self._counts: dict[str, int] = {}
        self._total = 0

    def note(self, item: T) -> None:
        v = self._classify(item) or self._unknown
        self._pending.append(v)
        self._counts[v.key] = self._counts.get(v.key, 0) + 1
        self._total += 1
        if self._time_to_flush(len(self._pending)):
            self._flush()

    def _flush(self) -> None:
        if not self._pending:
            return
        m = marker_rich if self._rich else marker_ansi
        self._log(f'    {"".join(m(v) for v in self._pending)}  ({self._total})')
        self._pending.clear()
        self._stamp()

    def summary(self) -> str:
        if not self._counts:
            return f'no {self._noun} found'
        parts = [f'{self._counts.get(v.key, 0)} {v.key}'
                 for v in self._categories if self._counts.get(v.key)]
        other = self._counts.get(self._unknown.key, 0)
        if other:
            parts.append(f'{other} {self._unknown.key}')
        return f'found {self._total} {self._noun}: ' + ', '.join(parts)

    def close(self) -> None:
        if self._total == 0 and not self._pending:
            return
        self._flush()
        self._log('  ' + self.summary())
