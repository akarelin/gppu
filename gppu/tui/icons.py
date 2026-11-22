"""Canonical state glyphs + spinner frame sets.

Every gppu TUI should render the same visual vocabulary for worker state,
reachability, pass/fail, and generic "thinking" spinners.  Keeping the
glyphs in one place avoids per-app drift (preservator using ✓, another app
using ✅, a third using OK).

Two families:

- :data:`STATE_GLYPHS` — discrete state markers.  Accessed by key
  (``'running'``, ``'ok'`` …) to get a ``(symbol, rich_color, ansi_code)``
  triple.  Convenience :func:`glyph_rich` / :func:`glyph_ansi` format one.
- :data:`SPINNERS` — named frame sequences.  :class:`gppu.tui.SpinnerIndicator`
  already uses Braille dots for background processes; this module exposes
  named variants (``dots``, ``line``, ``arc``, ``triangle``) so widgets
  with different density needs can pick appropriately.

Import style::

    from gppu.tui.icons import STATE_GLYPHS, glyph_rich, SPINNERS

    label = glyph_rich('ok') + ' pulled'
    widget.spinner_frames = SPINNERS['arc']
"""

from __future__ import annotations

from typing import NamedTuple


class Glyph(NamedTuple):
    symbol: str          # .. one-char glyph
    rich_color: str      # .. Rich markup color name ('bright_green', 'dim white')
    ansi_code: str       # .. SGR params for plain ANSI ('38;5;10')


# .. ── state markers ──────────────────────────────────────────────────────────

# region - state keys
# .. Keys chosen to match common worker/task lifecycle vocabulary.
# .. Add to this dict as new states become needed; never re-home existing keys.
# endregion
STATE_GLYPHS: dict[str, Glyph] = {
    # .. Generic task lifecycle
    'pending':  Glyph('○', 'dim white',      '38;5;8'),
    'queued':   Glyph('◌', 'dim white',      '38;5'),
    'running':  Glyph('◐', 'bright_yellow',  '38;5;11'),
    'ok':       Glyph('✓', 'bright_green',   '38;5;10'),
    'fail':     Glyph('✗', 'bright_red',     '38;5;9'),
    'canceled': Glyph('⊘', 'dim white',      '38;5;8'),
    'skipped':  Glyph('–', 'dim white',      '38;5;8'),

    # .. Reachability / connectivity (preservator TUI uses these)
    'reachable':   Glyph('●', 'bright_green', '38;5;10'),
    'unreachable': Glyph('●', 'bright_red',   '38;5;9'),
    'probing':     Glyph('⟳', 'yellow',        '38;5;3'),

    # .. Warnings / notes
    'warn':   Glyph('⚠', 'bright_yellow', '38;5;11'),
    'info':   Glyph('ℹ', 'bright_cyan',   '38;5;14'),
    'error':  Glyph('✗', 'bright_red',    '38;5;9'),
}


def marker_rich(marker: Glyph) -> str:
    """Rich-markup symbol of a Glyph, or of a progress Marker — ``[bright_cyan]✻[/]``."""
    return f'[{marker.rich_color}]{marker.symbol}[/]'


def marker_ansi(marker: Glyph) -> str:
    """Raw ANSI-escaped symbol — used when writing to a plain terminal."""
    return f'\x1b[{marker.ansi_code}m{marker.symbol}\x1b[0m'


def glyph_rich(key: str) -> str:
    """Rich-markup glyph by state key — ``[bright_green]✓[/]``.

    Unknown keys render as a dim ``?`` rather than raising — easier to
    tolerate drift than to stop the TUI.
    """
    g = STATE_GLYPHS.get(key)
    if g is None:
        return '[dim]?[/]'
    return marker_rich(g)


def glyph_ansi(key: str) -> str:
    """Raw-ANSI glyph by state key."""
    g = STATE_GLYPHS.get(key)
    if g is None:
        return '?'
    return marker_ansi(g)


# .. ── spinner frame sequences ────────────────────────────────────────────────

SPINNERS: dict[str, str] = {
    # region - braille dots
    # .. Braille dots — dense, smooth, default choice.
    # .. Matches the set already used by gppu.tui.SpinnerIndicator.
    # endregion
    'dots':     '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏',

    # .. Clock-like line: thin, works in narrow columns.
    'line':     '|/-\\',

    # .. Arcs — slightly more visible than dots on dark terminals.
    'arc':      '◜◠◝◞◡◟',

    # .. Triangle — emphatic; useful for a single focal indicator.
    'triangle': '▹▸▶▸',

    # .. Pulse — 2-frame breathing dot; minimal motion, good for per-row.
    'pulse':    '○●',
}


def spinner_frames(name: str = 'dots') -> str:
    """Lookup helper — unknown name falls back to ``'dots'``."""
    return SPINNERS.get(name, SPINNERS['dots'])
