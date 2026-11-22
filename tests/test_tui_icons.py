"""Tests for gppu.tui.icons: the state glyphs."""
from __future__ import annotations

import pytest

from gppu.tui.icons import STATE_GLYPHS, Glyph, glyph_rich


class TestStateGlyphs:
    def test_every_state_is_valid_triple(self):
        for key, g in STATE_GLYPHS.items():
            assert isinstance(g, Glyph)
            assert isinstance(g.symbol, str)
            assert len(g.symbol) == 1, f'{key}: symbol should be 1 char'
            assert g.rich_color, f'{key}: missing rich_color'
            assert g.ansi_code, f'{key}: missing ansi_code'

    def test_required_keys_present(self):
        # .. Core lifecycle states every consumer relies on
        for required in ('pending', 'running', 'ok', 'fail', 'canceled',
                         'reachable', 'unreachable', 'warn', 'info', 'error'):
            assert required in STATE_GLYPHS, f'missing state: {required}'


class TestRichAndAnsiHelpers:
    def test_rich_format(self):
        assert glyph_rich('ok') == '[bright_green]✓[/]'
        assert glyph_rich('fail') == '[bright_red]✗[/]'

    def test_unknown_key_falls_back(self):
        assert glyph_rich('not_a_state') == '[dim]?[/]'
