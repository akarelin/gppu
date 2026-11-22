"""Tests for gppu.tui.progress: TickProgress, and the markers' helpers."""
from __future__ import annotations

import pytest

from gppu.tui.icons import marker_ansi
from gppu.tui.progress import TickProgress, Marker, legend_ansi


# .. ── TickProgress ──────────────────────────────────────────────────────────

class TestTickProgress:
    def test_batches_and_summary(self):
        lines: list[str] = []
        p = TickProgress(lines.append, tick_every=3)
        for _ in range(7):
            p.note()
        p.close()
        # .. final line is the summary
        assert lines[-1] == '    discovered 7 items'
        # .. running total visible in some strip
        assert any('(7)' in l for l in lines)
        # .. markup format
        assert all('[dim]·[/]' in l or 'discovered' in l for l in lines)

    def test_zero_notes_is_silent(self):
        lines: list[str] = []
        TickProgress(lines.append).close()
        assert lines == []

    def test_ansi_mode(self):
        lines: list[str] = []
        p = TickProgress(lines.append, rich=False, tick_every=5)
        for _ in range(3):
            p.note()
        p.close()
        assert any('\x1b[' in l for l in lines)


# .. ── MarkerProgress ────────────────────────────────────────────────────────

_RED   = Marker('red',  'Red',  '●', 'red',  '31')
_BLUE  = Marker('blue', 'Blue', '◆', 'blue', '34')
_UNK   = Marker('other', 'other', '·', 'dim', '90')


# .. ── helpers ──────────────────────────────────────────────────────────────

class TestHelpers:
    def test_marker_ansi_includes_escape(self):
        out = marker_ansi(_BLUE)
        assert out.startswith('\x1b[34m') and out.endswith('\x1b[0m')

    def test_legend_ansi_contains_escapes(self):
        assert '\x1b[' in legend_ansi((_RED,))
