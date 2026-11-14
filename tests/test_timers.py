"""An app's timers, Y2's: one thread holds them, a callback fires once or at an interval, a key re-arms."""
import threading
from unittest.mock import Mock, patch

import pytest

from gppu import App, TimerHandle
from gppu.app import mixin_Stepper
from gppu.gppu import _DC


def wait(event: threading.Event) -> bool:
    return event.wait(5)


def test_a_timer_fires_once_with_the_keywords_its_callback_takes():
    app, heard, fired = App(name='timers'), [], threading.Event()

    def callback(level):
        heard.append(level)
        fired.set()

    handle = app.run_later(callback, delay=0.01, key='lamp', level=30, ignored='x')
    assert isinstance(handle, TimerHandle) and handle.kind == 'once' and handle.name == 'callback'
    assert app.timers == {handle.id: handle} and app.h_timeouts == {'lamp': handle}
    assert wait(fired)
    assert heard == [30]
    assert not handle.running
    assert app.timers == {} and app.h_timeouts == {}     # a spent one-shot is no longer filed as armed


def test_arming_a_key_again_replaces_the_timer_armed_under_it():
    app, heard, fired = App(name='timers'), [], threading.Event()
    first = app.run_later(lambda: heard.append('first'), delay=0.05, key='occupancy/hall')
    second = app.run_later(lambda: (heard.append('second'), fired.set()), delay=0.01, key='occupancy/hall')
    assert not first.running and second.running
    assert app.timers == {second.id: second} and app.h_timeouts == {'occupancy/hall': second}
    assert wait(fired)
    threading.Event().wait(0.1)                           # past the first one's delay
    assert heard == ['second']


def test_a_timer_repeats_at_its_interval_until_cancelled():
    app, ticks, enough = App(name='timers'), [], threading.Event()

    def tick():
        ticks.append(1)
        if len(ticks) == 3: enough.set()

    handle = app.run_every(tick, start=0.01, interval=0.01)
    assert handle.kind == 'interval' and handle.interval == 0.01
    assert wait(enough)
    app.cancel_timer(handle)
    assert not app.timer_running(handle) and app.timers == {}


def test_cancel_timers_cancels_every_timer_the_app_armed():
    app = App(name='timers')
    handles = [app.run_later(lambda: None, delay=60, key='a'), app.run_later(lambda: None, delay=60),
               app.run_every(lambda: None, start=60, interval=60)]
    app.cancel_timers()
    assert not any(handle.running for handle in handles)
    assert app.timers == {} and app.h_timeouts == {}


def test_an_app_composes_with_a_data_object_that_has_steps():
    """Y2's State is an App and an entity, a _DC with steps: App's data comes first, and constructing the app
    initializes only its own data, leaving the entity's initialization to the class composing them."""
    class Entity(_DC, mixin_Stepper):
        def __init__(self, **kw):
            raise AssertionError('App initialized the entity')

    class State(App, Entity):
        pass

    state = State(name='State')
    assert state.name == 'State' and state.timers == {}


def test_a_failing_repeat_reports_its_failure_and_runs_the_next_time():
    app, callback = App(name='failed-poll'), Mock(side_effect=[ValueError('invalid device response'), None])
    with patch('gppu.gppu._SCHEDULER.arm') as arm:
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
    app = App(name='cancelled-poll')

    def callback():
        app.cancel_timer(handle)
        raise ValueError('invalid device response')

    with patch('gppu.gppu._SCHEDULER.arm') as arm:
        handle = app.run_every(callback, start=30, interval=60)
        fire = arm.call_args.args[1]
        arm.reset_mock()
        with pytest.raises(ValueError, match='invalid device response'):
            fire()
        arm.assert_not_called()
