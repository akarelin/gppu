"""Tests for gppu.tui.progress — TickProgress, MarkerProgress, Marker helpers."""
from __future__ import annotations

import pytest

from gppu.tui.progress import (
    TickProgress, MarkerProgress, Marker,
    marker_rich, marker_ansi, legend_rich, legend_ansi,
)


# ── TickProgress ──────────────────────────────────────────────────────────

class TestTickProgress:
    def test_batches_and_summary(self):
        lines: list[str] = []
        p = TickProgress(lines.append, tick_every=3)
        for _ in range(7):
            p.note()
        p.close()
        # final line is the summary
        assert lines[-1] == '    discovered 7 items'
        # running total visible in some strip
        assert any('(7)' in l for l in lines)
        # markup format
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


# ── MarkerProgress ────────────────────────────────────────────────────────

_RED   = Marker('red',  'Red',  '●', 'red',  '31')
_BLUE  = Marker('blue', 'Blue', '◆', 'blue', '34')
_UNK   = Marker('other', 'other', '·', 'dim', '90')


def _classify(n: int) -> Marker:
    if n < 5:
        return _RED
    if n < 10:
        return _BLUE
    return _UNK


class TestMarkerProgress:
    def test_classifies_and_summarizes(self):
        lines: list[str] = []
        m = MarkerProgress(lines.append, (_RED, _BLUE), _UNK, _classify,
                           tick_every=10, noun='nums')
        for n in [1, 2, 3, 6, 7, 11]:
            m.note(n)
        m.close()
        summary = lines[-1]
        assert 'found 6 nums' in summary
        assert '3 red' in summary
        assert '2 blue' in summary
        assert '1 other' in summary

    def test_rich_markup_present(self):
        lines: list[str] = []
        m = MarkerProgress(lines.append, (_RED,), _UNK, lambda x: _RED,
                           tick_every=2)
        for i in range(3):
            m.note(i)
        m.close()
        assert any('[red]●[/]' in l for l in lines)

    def test_ansi_mode(self):
        lines: list[str] = []
        m = MarkerProgress(lines.append, (_RED,), _UNK, lambda x: _RED,
                           tick_every=100, rich=False)
        for i in range(3):
            m.note(i)
        m.close()
        assert any('\x1b[31m' in l for l in lines)

    def test_zero_notes_silent(self):
        lines: list[str] = []
        MarkerProgress(lines.append, (_RED,), _UNK, lambda x: _RED).close()
        assert lines == []


# ── helpers ──────────────────────────────────────────────────────────────

class TestHelpers:
    def test_marker_rich_format(self):
        assert marker_rich(_RED) == '[red]●[/]'

    def test_marker_ansi_includes_escape(self):
        out = marker_ansi(_BLUE)
        assert out.startswith('\x1b[34m') and out.endswith('\x1b[0m')

    def test_legend_rich_lists_each(self):
        legend = legend_rich((_RED, _BLUE))
        assert '=Red' in legend and '=Blue' in legend

    def test_legend_ansi_contains_escapes(self):
        assert '\x1b[' in legend_ansi((_RED,))
