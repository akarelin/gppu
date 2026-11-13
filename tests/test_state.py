"""State, the program's state, and Runtime, the container of its apps."""
import pytest

from gppu import Env, Runtime, State, _Base, cache
from gppu import glob


@pytest.fixture(autouse=True)
def clean():
    State._my, State._listeners = {}, []
    Runtime.apps, Runtime._event_listeners = {}, []
    yield
    State._my, State._listeners = {}, []
    Runtime.apps, Runtime._event_listeners = {}, []


def test_state_is_an_app_apart_from_env():
    assert isinstance(State, _Base) and isinstance(Env, _Base)
    State.set('hosts/s2/online', True)
    assert State.my('hosts/s2/online') is True
    assert State.my_dict('hosts') == {'s2': {'online': True}}
    assert glob('hosts/s2/online') is None


def test_listeners_hear_their_path_and_what_is_under_or_above_it():
    heard = []
    State.listen(lambda **change: heard.append(('hosts', change)), 'hosts')
    State.listen(lambda **change: heard.append(('s5', change)), 'hosts/s5')
    unlisten = State.listen(lambda **change: heard.append(('all', change)))
    State.set('hosts/s2/online', True)
    State.set('hosts', {'s5': {'online': False}})
    unlisten()
    State.set('other', 1)
    assert heard == [
        ('hosts', {'path': 'hosts/s2/online', 'old': None, 'new': True}),
        ('all', {'path': 'hosts/s2/online', 'old': None, 'new': True}),
        ('hosts', {'path': 'hosts', 'old': {'s2': {'online': True}}, 'new': {'s5': {'online': False}}}),
        ('s5', {'path': 'hosts', 'old': {'s2': {'online': True}}, 'new': {'s5': {'online': False}}}),
        ('all', {'path': 'hosts', 'old': {'s2': {'online': True}}, 'new': {'s5': {'online': False}}}),
    ]


def test_an_unchanged_value_calls_no_listener():
    heard = []
    State.set('mode', 'day')
    State.listen(lambda **change: heard.append(change), 'mode')
    State.set('mode', 'day')
    assert heard == []


def test_a_value_is_not_a_parent():
    State.set('mode', 'day')
    with pytest.raises(TypeError):
        State.set('mode/sub', 1)


def test_runtime_holds_the_apps_and_carries_their_events():
    class Lights(_Base):
        def __init__(self, name): self.name = name
    first, second = Runtime.register_app(Lights('first')), Runtime.register_app(Lights('second'))
    assert list(Runtime.apps.items()) == [('first', first), ('second', second)]
    heard = []
    Runtime.listen_event(lambda **e: heard.append(('scene', e)), 'scene')
    unlisten = Runtime.listen_event(lambda **e: heard.append(('any', e)))
    Runtime.fire_event('scene', name='evening')
    unlisten()
    Runtime.fire_event('other')
    assert heard == [('scene', {'event': 'scene', 'data': {'name': 'evening'}}),
                     ('any', {'event': 'scene', 'data': {'name': 'evening'}})]


def test_caching_is_the_standard_library():
    import functools
    assert cache is functools.cache
