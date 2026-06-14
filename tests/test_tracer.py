"""Tests for the Y2 flight-recorder Tracer and _tracer decorators (gppu.app)."""
import json

import pytest

from gppu.app import Tracer, _tracer, TA_BEFORE, TA_AFTER, TA_INSTEAD


@pytest.fixture
def tracer(tmp_path):
    """Configure Tracer into a tmp folder; reset class-level state afterwards."""
    Tracer.configure(str(tmp_path), enabled=True)
    yield Tracer
    if Tracer._fh:
        Tracer._fh.close()
    Tracer._fh = None
    Tracer.enabled = False
    Tracer.path = None
    Tracer.folder = '.'


def _lines(tracer):
    tracer._fh.flush()
    with open(tracer.path) as f:
        return [json.loads(line) for line in f if line.strip()]


class TestTracer:
    def test_record_writes_jsonl(self, tracer):
        tracer.record('test', a=1)
        recs = _lines(tracer)
        assert len(recs) == 1
        assert recs[0]['kind'] == 'test'
        assert recs[0]['a'] == 1
        assert 'ts' in recs[0]

    def test_disabled_is_noop(self, tmp_path):
        Tracer.configure(str(tmp_path), enabled=False)
        Tracer.record('test', a=1)
        assert Tracer.enabled is False
        assert Tracer._fh is None

    def test_snapshot_object(self, tracer):
        class Obj:
            name = 'thing'
            data = {'k': 'v'}
        tracer.snapshot_object(Obj(), 'init')
        rec = _lines(tracer)[0]
        assert rec['kind'] == 'object'
        assert rec['klass'] == 'TestTracer.test_snapshot_object.<locals>.Obj'
        assert rec['name'] == 'thing'
        assert rec['stage'] == 'init'
        assert rec['data'] == {'k': 'v'}

    def test_trigger_event_seq_linkage(self, tracer):
        tracer.trigger('mqtt', {'event_type': 'MQTT_MESSAGE', 'data': {'topic': 'a/b'}})
        tracer.event('app1', {'type': 'event', 'function': None, 'event': 'MQTT_MESSAGE', 'data': {}})
        trig, ev = _lines(tracer)
        assert trig['kind'] == 'trigger' and ev['kind'] == 'event'
        assert trig['seq'] == ev['seq']

    def test_trigger_skips_internal_and_admin(self, tracer):
        tracer.trigger('admin', {'event_type': 'state_changed', 'data': {}})
        tracer.trigger('default', {'event_type': '__AD_INTERNAL', 'data': {}})
        assert _lines(tracer) == []

    def test_trigger_state_changed_shape(self, tracer):
        tracer.trigger('yala', {'event_type': 'state_changed', 'data': {
            'entity_id': 'light.x',
            'old_state': {'state': 'off'}, 'new_state': {'state': 'on'}}})
        rec = _lines(tracer)[0]
        assert rec['entity'] == 'light.x'
        assert rec['old'] == 'off' and rec['new'] == 'on'


class TestTracerDecorator:
    def _spied(self, action):
        calls = []
        def spy(self, *a, **kw): calls.append('spy')
        class C:
            @_tracer(spy, action)
            def m(self):
                calls.append('m')
                return 'ret'
        return C(), calls

    def test_before(self):
        obj, calls = self._spied(TA_BEFORE)
        assert obj.m() == 'ret'
        assert calls == ['spy', 'm']

    def test_after(self):
        obj, calls = self._spied(TA_AFTER)
        assert obj.m() == 'ret'
        assert calls == ['m', 'spy']

    def test_instead(self):
        obj, calls = self._spied(TA_INSTEAD)
        assert obj.m() is None
        assert calls == ['spy']

    def test_no_tracer_passthrough(self):
        class C:
            @_tracer(None, TA_BEFORE)
            def m(self): return 42
        assert C().m() == 42
