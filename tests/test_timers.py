"""An async app's timers: one thread holds them, a callback fires once or at an interval, a key re-arms."""
import threading
from unittest.mock import Mock, patch

import pytest

from gppu import App, AsyncApp, TimerHandle
from gppu.app import YStart
from gppu.gppu import _DC


def wait(event: threading.Event) -> bool:
    return event.wait(5)


def test_a_timer_fires_once_with_the_keywords_its_callback_takes():
    app, heard, fired = AsyncApp(name='timers'), [], threading.Event()

    def callback(level):
        heard.append(level)
        fired.set()

    handle = app.run_later(callback, delay=0.01, key='lamp', level=30, ignored='x')
    assert isinstance(handle, TimerHandle) and handle.kind == 'once' and handle.name == 'callback'
    assert app.timers == {handle.id: handle} and app.h_timeouts == {'lamp': handle}
    assert wait(fired)
    assert heard == [30]
    assert not handle.running
    assert app.timers == {} and app.h_timeouts == {}     # .. a spent one-shot is no longer filed as armed


def test_arming_a_key_again_replaces_the_timer_armed_under_it():
    app, heard, fired = AsyncApp(name='timers'), [], threading.Event()
    first = app.run_later(lambda: heard.append('first'), delay=0.05, key='occupancy/hall')
    second = app.run_later(lambda: (heard.append('second'), fired.set()), delay=0.01, key='occupancy/hall')
    assert not first.running and second.running
    assert app.timers == {second.id: second} and app.h_timeouts == {'occupancy/hall': second}
    assert wait(fired)
    threading.Event().wait(0.1)                           # .. past the first one's delay
    assert heard == ['second']


def test_a_timer_repeats_at_its_interval_until_cancelled():
    app, ticks, enough = AsyncApp(name='timers'), [], threading.Event()

    def tick():
        ticks.append(1)
        if len(ticks) == 3: enough.set()

    handle = app.run_every(tick, start=0.01, interval=0.01)
    assert handle.kind == 'interval' and handle.interval == 0.01
    assert wait(enough)
    app.cancel_timer(handle)
    assert not app.timer_running(handle) and app.timers == {}


def test_cancel_timers_cancels_every_timer_the_app_armed():
    app = AsyncApp(name='timers')
    handles = [app.run_later(lambda: None, delay=60, key='a'), app.run_later(lambda: None, delay=60),
               app.run_every(lambda: None, start=60, interval=60)]
    app.cancel_timers()
    assert not any(handle.running for handle in handles)
    assert app.timers == {} and app.h_timeouts == {}


def test_an_app_initializes_the_class_it_is_composed_with():
    """App's init is cooperative: a class composed after it, as Linked Data's API composes its database or Y2's State
    its entity, is initialized with what App does not take."""
    class Entity(YStart, _DC):
        def __init__(self, *, eid, **kw):
            super().__init__(**kw)
            self.eid = eid

    class State(App, Entity):
        pass

    state = State(name='State', eid='app.state@system')
    assert (state.name, state.eid) == ('State', 'app.state@system')


def test_a_failing_repeat_reports_its_failure_and_runs_the_next_time():
    app, callback = AsyncApp(name='failed-poll'), Mock(side_effect=[ValueError('invalid device response'), None])
    with patch('gppu.app._SCHEDULER.arm') as arm:
        handle = app.run_every(callback, start=30, interval=60)
        fire = arm.call_args.args[1]
        arm.reset_mock()
        with pytest.raises(ValueError, match='invalid device response'):
            fire()
        arm.assert_called_once_with(handle, fire, 60)
        arm.call_args.args[1]()
        assert callback.call_count == 2
        app.cancel_timer(handle)


def test_a_repeat_cancelled_while_failing_does_not_arm_again():
    app = AsyncApp(name='cancelled-poll')

    def callback():
        app.cancel_timer(handle)
        raise ValueError('invalid device response')

    with patch('gppu.app._SCHEDULER.arm') as arm:
        handle = app.run_every(callback, start=30, interval=60)
        fire = arm.call_args.args[1]
        arm.reset_mock()
        with pytest.raises(ValueError, match='invalid device response'):
            fire()
        arm.assert_not_called()


def test_an_app_that_is_not_running_stops_from_any_thread():
    app, stopped = AsyncApp(name='idle'), threading.Event()
    threading.Thread(target=lambda: (app.stop(), stopped.set())).start()
    assert wait(stopped) and app.stopped


def test_a_running_app_stopped_from_another_thread_cancels_what_it_spawned():
    """Y2's Supervisor restarts an app from a timer's thread, where no loop runs."""
    import asyncio

    class Serving(AsyncApp):
        def start(self):
            super().start()
            self._spawn(asyncio.Event().wait())

    app = Serving(name='serving')

    async def run():
        asyncio.get_running_loop().call_later(0.05, lambda: threading.Thread(target=app.stop).start())
        await asyncio.wait_for(app.run(), 5)

    asyncio.run(run())
    assert app.stopped
