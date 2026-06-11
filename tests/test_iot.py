"""Tests for gppu.iot mqtt plumbing (offline — no broker)."""
from gppu.iot import mqtt_connstring, MqttMixin, MQTT_CONN_FIELDS


class TestMqttConnstring:
    def test_filters_to_client_kwargs(self):
        conn = {
            'hostname': 'mqtt.example', 'port': 1883,
            'username': 'svc', 'password': 'pw', 'identifier': 'svc',
            'status_topic': 'status/svc', 'listen': ['a/#'],
        }
        cs = mqtt_connstring(conn)
        assert set(cs) == MQTT_CONN_FIELDS
        assert cs['hostname'] == 'mqtt.example'
        assert 'status_topic' not in cs and 'listen' not in cs

    def test_partial_block_passes_through(self):
        assert mqtt_connstring({'hostname': 'h'}) == {'hostname': 'h'}

    def test_empty(self):
        assert mqtt_connstring({}) == {}


class TestTopicMatches:
    def test_exact(self):
        assert MqttMixin._topic_matches('a/b/c', 'a/b/c')
        assert not MqttMixin._topic_matches('a/b/c', 'a/b')

    def test_hash_wildcard_prefix(self):
        assert MqttMixin._topic_matches('a/b/c', 'a/#')
        assert MqttMixin._topic_matches('a/b', 'a/b/#')  # prefix match
        assert not MqttMixin._topic_matches('x/b/c', 'a/#')


class TestDCRegistration:
    def test_y2_types_registered(self):
        from gppu.gppu import _DC, _DC_BASE_TYPE_MAP
        from gppu.iot import y2eid, y2topic
        assert _DC_BASE_TYPE_MAP['y2eid'] is y2eid
        assert _DC_BASE_TYPE_MAP['y2topic'] is y2topic
        assert _DC._DC_TYPE_MAP['y2eid'] is y2eid
        assert _DC._DC_TYPE_MAP['y2topic'] is y2topic


class TestTopLevelExports:
    def test_reexports(self):
        import gppu
        for name in ('y2list', 'y2path', 'y2topic', 'y2slug', 'y2eid',
                     'mqtt_connstring', 'MqttMixin', 'Transformer'):
            assert hasattr(gppu, name), name
