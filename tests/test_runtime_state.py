"""Tests for DataObject tree, State registry, Runtime (launch/run_parallel/call), and ServiceApp dry_run."""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

from gppu import App, DataObject, Runtime, ServiceApp, State


class _Child(DataObject):
    def __init(self) -> None:
        self.events: list[str] = []

    def __load(self) -> None:
        self.events.append('load')

    def __start(self) -> None:
        self.events.append('start')

    def __stop(self) -> None:
        self.events.append('stop')

    def ping(self, x: int) -> int:
        return x + 1


class _Parent(App):
    def __init(self) -> None:
        self.child_a = _Child(name='a', parent=self)
        self.child_b = _Child(name='b', parent=self)


def test_dataobject_tree_and_lifecycle_cascade() -> None:
    app = _Parent()
    assert [c.name for c in app.children] == ['a', 'b']
    assert app.child('a') is app.child_a
    assert app.child('missing') is None

    async def exercise() -> None:
        await app.load()
        await app.start()
        app.stop()

    asyncio.run(exercise())
    assert app.child_a.events == ['load', 'start', 'stop']
    assert app.child_b.events == ['load', 'start', 'stop']


def test_state_registry_and_runtime_call() -> None:
    State.reset()
    child = _Child(name='target')
    State.register('demo.target', child)
    assert State.get_object('demo.target') is child
    with pytest.raises(ValueError):
        State.register('demo.target', child)
    assert asyncio.run(Runtime.call('demo.target', 'ping', 41)) == 42
    State.unregister('demo.target')
    with pytest.raises(KeyError):
        State.get_object('demo.target')


def test_runtime_launch_and_run_parallel(tmp_path) -> None:
    lines: list[str] = []

    async def exercise() -> None:
        err = await Runtime.launch([sys.executable, '-c', 'print("hello-runtime")'], lines.append, tmp_path)
        assert err is None
        assert lines == ['hello-runtime']

        async def work(n: int) -> int:
            await asyncio.sleep(0.01)
            return n * 2

        assert await Runtime.run_parallel([work(1), work(2), work(3)]) == [2, 4, 6]

        done: list[str] = []
        async def run_unit(u: str) -> None:
            await asyncio.sleep(0.01)
            done.append(u)

        await Runtime.run_parallel(['u1', 'u2'], run_unit)
        assert set(done) == {'u1', 'u2'}

    asyncio.run(exercise())


def test_serviceapp_dry_run_blocks_mqtt_publish() -> None:
    svc = ServiceApp(name='svc', dry_run=True)
    fake_client = AsyncMock()
    svc._client = fake_client
    asyncio.run(svc.mqtt_publish('test/topic', 'hello', retain=True))
    fake_client.publish.assert_not_called()
