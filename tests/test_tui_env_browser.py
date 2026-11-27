"""Tests for gppu.tui.env_browser: Env validation and navigable dict TUI."""

from __future__ import annotations

import pytest

from gppu.tui.env_browser import EnvBrowser, validate_env


def test_validate_ran_env():
    res = validate_env('RAN')
    assert res.ok, res.errors
    assert res.environment == 'RAN'
    assert res.files
    assert isinstance(res.data, dict) and res.data
    assert any(v.endswith('.yaml') or '.yaml:' in v for v in res.sources.values())


def test_validate_iot_env():
    res = validate_env('IoT')
    assert res.ok, res.errors
    assert res.environment == 'IoT'
    assert 'groups' in res.data
    assert res.files


@pytest.mark.asyncio
async def test_env_browser_tui_mounts_switches_hides_templates_and_shows_source():
    from gppu.tui.tree_table import TreeTable
    from textual.widgets import TextArea
    app = EnvBrowser(environment='RAN')
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one('#tree', TreeTable)
        assert len(tree._visible) > 1
        assert all('dict (' not in node.entry.label for node in tree._visible)
        assert app._adapter.source_of('host') == 'Env (machine)'
        await pilot.press('e')
        await pilot.pause()
        assert app._result.environment == 'IoT'
        tree.expand('groups')
        await pilot.pause()
        labels_before = {node.entry.label for node in tree._visible}
        assert 'templates' in labels_before
        await pilot.press('t')
        await pilot.pause()
        assert app._hide_templates is True
        tree.expand('groups')
        await pilot.pause()
        labels_after = {node.entry.label for node in tree._visible}
        assert 'templates' not in labels_after
        tree.select('groups')
        await pilot.pause()
        detail = app.query_one('#detail', TextArea).text
        assert '\ntemplates:' not in detail and not detail.startswith('templates:')
