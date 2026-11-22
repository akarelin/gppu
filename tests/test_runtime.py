"""Runtime, Y2's: the program's apps by name, and the listeners to events, to entity states and to topics."""
from types import SimpleNamespace

import pytest

from gppu import AsyncApp, Env, ListenerHandle, Runtime, StateManager, y2eid, y2path


@pytest.fixture(autouse=True)
def clean():
    Runtime.reset()
    yield
    Runtime.reset()


class Lights(AsyncApp):
    def __init__(self, **kw):
        super().__init__(**kw)
        Runtime.register_app(self)


def test_runtime_holds_the_apps_and_carries_their_events():
    first, second = Lights(name='first'), Lights(name='second')
    assert list(Runtime.apps.items()) == [('first', first), ('second', second)]
    heard = []
    Runtime.listen_event(lambda event, data: heard.append(('scene', event, data)), event='scene')
    handle = Runtime.listen_event(lambda event, data: heard.append(('any', event, data)))
    assert isinstance(handle, ListenerHandle)
    Runtime.fire_event('scene', name='evening')
    handle.cancel()
    Runtime.fire_event('other')
    assert heard == [('scene', 'scene', {'name': 'evening'}), ('any', 'scene', {'name': 'evening'})]


def test_a_state_listener_hears_its_entity_and_attribute():
    heard = []
    Runtime.listen_state(lambda attribute, old, new: heard.append((attribute, old, new)), eid='light.ao@yala')
    Runtime.listen_state(lambda attribute, old, new: heard.append(('*', attribute, new)), eid='light.ao@yala', attribute='*')
    light = SimpleNamespace(eid=y2eid('light.ao@yala'), state='on', attributes={'brightness': 128})
    Runtime.state_changed(light, old_state='off', old_attrs={'brightness': 64})
    other = SimpleNamespace(eid=y2eid('light.hall@yala'), state='on', attributes={})
    Runtime.state_changed(other, old_state='off', old_attrs={})
    assert heard == [(None, 'off', 'on'), ('*', None, 'on'), ('*', 'brightness', 128)]


def test_a_topic_listener_hears_a_change_on_its_path():
    heard = []
    handle = Runtime.listen_topic_state(lambda path, old, new: heard.append((str(path), old, new)), path='sensor/motion/hall')
    Runtime.topic_changed(y2path('sensor/motion/hall'), old=0, new=1)
    Runtime.topic_changed(y2path('sensor/motion/hall'), old=1, new=1)     # .. no change, nothing heard
    Runtime.topic_changed(y2path('sensor/motion/den'), old=0, new=1)
    handle.cancel()
    Runtime.topic_changed(y2path('sensor/motion/hall'), old=1, new=0)
    assert heard == [('sensor/motion/hall', 0, 1)]


def test_restart_starts_a_fresh_app_and_refuses_what_it_cannot_restart():
    class Fixed(Lights):
        restartable = False

    old = Lights(name='lights')
    old.start()
    new = Runtime.restart_app('lights')
    assert new is not old and type(new) is Lights and new.started and old.stopped
    assert Runtime.apps['lights'] is new
    Fixed(name='fixed')
    with pytest.raises(ValueError, match='App is not restartable: fixed'):
        Runtime.restart_app('fixed')
    with pytest.raises(ValueError, match='Unknown app: nobody'):
        Runtime.restart_app('nobody')


def test_reset_cancels_every_apps_timers_and_empties_the_runtime():
    app = Lights(name='lights')
    handle = app.run_later(lambda: None, delay=60)
    Runtime.actions['ao/on'] = ['light.ao@yala']
    Runtime.reset()
    assert not handle.running
    assert Runtime.apps == {} and Runtime.actions == {} and Runtime.state_listeners == {}
