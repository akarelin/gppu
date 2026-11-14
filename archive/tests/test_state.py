"""State, the program's state, and Runtime, the container of its apps."""
import pytest

from gppu import Runtime, State, _Base, cache
from gppu import glob


@pytest.fixture(autouse=True)
def clean():
    State.values = {}
    Runtime.apps, Runtime._event_listeners = {}, []
    yield
    State.values = {}
    Runtime.apps, Runtime._event_listeners = {}, []


def test_state_is_apart_from_the_configuration():
    State.set('hosts/s2/online', True)
    assert State.get('hosts/s2/online') is True
    assert State.get('hosts') == {'s2': {'online': True}}
    assert glob('hosts/s2/online') is None


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
