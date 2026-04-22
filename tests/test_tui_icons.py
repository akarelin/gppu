"""Tests for gppu.tui.icons — state glyphs + spinner frames."""
from __future__ import annotations

import pytest

from gppu.tui.icons import (
    STATE_GLYPHS, SPINNERS, Glyph,
    glyph_rich, glyph_ansi, spinner_frames,
)


class TestStateGlyphs:
    def test_every_state_is_valid_triple(self):
        for key, g in STATE_GLYPHS.items():
            assert isinstance(g, Glyph)
            assert isinstance(g.symbol, str)
            assert len(g.symbol) == 1, f'{key}: symbol should be 1 char'
            assert g.rich_color, f'{key}: missing rich_color'
            assert g.ansi_code, f'{key}: missing ansi_code'

    def test_required_keys_present(self):
        # Core lifecycle states every consumer relies on
        for required in ('pending', 'running', 'ok', 'fail', 'canceled',
                         'reachable', 'unreachable', 'warn', 'info', 'error'):
            assert required in STATE_GLYPHS, f'missing state: {required}'


class TestRichAndAnsiHelpers:
    def test_rich_format(self):
        assert glyph_rich('ok') == '[bright_green]✓[/]'
        assert glyph_rich('fail') == '[bright_red]✗[/]'

    def test_unknown_key_falls_back(self):
        assert glyph_rich('not_a_state') == '[dim]?[/]'
        assert glyph_ansi('not_a_state') == '?'

    def test_ansi_includes_escape(self):
        out = glyph_ansi('running')
        assert out.startswith('\x1b[') and out.endswith('\x1b[0m')


class TestSpinners:
    def test_all_named_sets_non_empty(self):
        for name, frames in SPINNERS.items():
            assert len(frames) >= 2, f'{name}: needs at least 2 frames'

    def test_lookup_and_fallback(self):
        assert spinner_frames('dots') == SPINNERS['dots']
        # unknown falls back to dots
        assert spinner_frames('nonexistent-spinner') == SPINNERS['dots']

    def test_required_sets_present(self):
        for required in ('dots', 'line', 'arc', 'pulse'):
            assert required in SPINNERS
