"""Canonical state glyphs.

Every gppu TUI renders the same glyphs for worker state, reachability and pass/fail: :data:`STATE_GLYPHS`, by key
(``'running'``, ``'ok'`` …), each a ``(symbol, rich_color, ansi_code)`` triple; :func:`glyph_rich` formats one.

    from gppu.tui.icons import glyph_rich

    label = glyph_rich('ok') + ' pulled'
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
