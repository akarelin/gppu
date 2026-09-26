"""Tests for gppu.tui.viz.heatmap — pure-fn rendering + timestamp folding."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from gppu.tui.viz.heatmap import render_heatmap_lines, counts_from_timestamps


class TestRenderHeatmap:
    def test_emits_7_weekday_rows_plus_header_and_total(self):
        counts = {date.today(): 3}
        lines = render_heatmap_lines(counts, days=30)
        weekday_rows = [l for l in lines if l.startswith('  Mon')
                        or l.startswith('  Tue') or l.startswith('  Wed')
                        or l.startswith('  Thu') or l.startswith('  Fri')
                        or l.startswith('  Sat') or l.startswith('  Sun')]
        assert len(weekday_rows) == 7

    def test_totals_line_matches_input(self):
        today = date.today()
        counts = {today - timedelta(days=i): i + 1 for i in range(5)}
        lines = render_heatmap_lines(counts, days=30)
        # 1+2+3+4+5 = 15
        assert any('total activity: 15' in l for l in lines)
        assert any('active days: 5/30' in l for l in lines)

    def test_empty_counts(self):
        lines = render_heatmap_lines({}, days=7)
        assert any('total activity: 0' in l for l in lines)
        assert any('active days: 0/7' in l for l in lines)

    def test_custom_title_and_unit(self):
        lines = render_heatmap_lines({}, days=10,
                                     title='Commits', unit='commits')
        assert lines[0] == '[bold]Commits — last 10 days[/]'
        assert any('commits' in l for l in lines[-2:])

    def test_title_can_be_suppressed(self):
        lines = render_heatmap_lines({}, days=10, title=None)
        # No bold header
        assert not any(l.startswith('[bold]') for l in lines)


class TestCountsFromTimestamps:
    def test_folds_iso_strings(self):
        d = date(2026, 4, 20)
        counts = counts_from_timestamps([
            '2026-04-20T00:00:00Z',
            '2026-04-20T23:59:59+00:00',
        ])
        assert counts == {d: 2}

    def test_accepts_datetime_objects(self):
        d = date(2026, 4, 20)
        counts = counts_from_timestamps([
            datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 20, 15, 0, tzinfo=timezone.utc),
        ])
        assert counts == {d: 2}

    def test_skips_unparseable(self):
        counts = counts_from_timestamps(['junk', None, 42, 'also bad'])
        assert counts == {}

    def test_mixed_input_types(self):
        d = date(2026, 4, 20)
        counts = counts_from_timestamps([
            '2026-04-20T00:00:00Z',
            datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            'junk',
        ])
        assert counts == {d: 2}
