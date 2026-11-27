"""Tests for gppu.tui.env_browser: Env validation and navigable dict TUI."""

from __future__ import annotations

import pytest

from gppu.tui.env_browser import EnvBrowser, validate_env


def test_validate_ran_env():
    res = validate_env('RAN')
    assert res.ok, res.errors
    assert res.environment == 'RAN'
    assert 'management' in res.data and 'hosts' in res.data['management']
    assert 'server_mounts' in res.data
    assert res.data['management']['hosts']['seven']['mounts']['/mnt/S1/Lake'] == '//s1.karel.in/Lake'
    assert '/mnt/yellow/config' in res.data['management']['hosts']['iot']['mounts']


def test_validate_iot_env():
    res = validate_env('IoT')
    assert res.ok, res.errors
    assert res.environment == 'IoT'
    assert 'groups' in res.data
    ao = next(r for r in res.data['groups']['ao'] if r.get('slug') == 'ao_desklamp')
    assert ao['listen_topic'] == 'devices/esp/$dashed'
    assert ao['command_topic'] == 'devices/esp/$dashed/set'
    from gppu import render_template
    assert render_template(ao['listen_topic'], ao) == 'devices/esp/ao-desklamp'
    assert render_template(ao['command_topic'], ao) == 'devices/esp/ao-desklamp/set'


@pytest.mark.asyncio
async def test_env_browser_tui_mounts_switches_hides_templates_and_shows_source():
    from gppu.tui.tree_table import TreeTable
    app = EnvBrowser(environment='RAN')
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one('#tree', TreeTable)
        assert len(tree._visible) > 1
        assert all('dict (' not in node.entry.label for node in tree._visible)
        assert 'config.yaml:' in app._adapter.source_of('server_mounts')
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
        from textual.widgets import TextArea
        tree.select('groups')
        await pilot.pause()
        detail = app.query_one('#detail', TextArea).text
        assert '\ntemplates:' not in detail and not detail.startswith('templates:')
