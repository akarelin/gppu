"""Tests for _PersistentDC and the Persistence factory (gppu.data)."""
import pytest

from gppu.data import _PersistentDC, Persistence


class FakeBackend:
    def __init__(self):
        self.rows = {}

    def upsert(self, cls, key, data): self.rows[(cls, key)] = dict(data)
    def load(self, cls, key): return self.rows.get((cls, key))
    def iter(self, cls):
        for (c, k), d in self.rows.items():
            if c == cls: yield k, d
    def delete(self, cls, key): self.rows.pop((cls, key), None)
    def close(self): pass


@pytest.fixture
def DC():
    """Fresh _PersistentDC subclass per test — bind_db sets class-level state."""
    class Thing(_PersistentDC):
        _persist_key = 'name'
    return Thing


class TestPersistentDC:
    def test_persist_upserts_by_key(self, DC):
        db = FakeBackend()
        DC.bind_db(db)
        DC(data={'name': 'x', 'v': 1}).persist()
        assert db.rows[('Thing', 'x')] == {'name': 'x', 'v': 1}

    def test_persist_without_key_is_noop(self, DC):
        db = FakeBackend()
        DC.bind_db(db)
        DC(data={'v': 1}).persist()
        assert db.rows == {}

    def test_unbound_is_noop(self, DC):
        DC(data={'name': 'x'}).persist()   # no bind_db — must not raise
        assert DC.load('x') is None

    def test_load(self, DC):
        db = FakeBackend()
        DC.bind_db(db)
        DC(data={'name': 'x', 'v': 2}).persist()
        assert DC.load('x') == {'name': 'x', 'v': 2}
        assert DC.load('missing') is None

    def test_iter_all(self, DC):
        db = FakeBackend()
        DC.bind_db(db)
        DC(data={'name': 'a'}).persist()
        DC(data={'name': 'b'}).persist()
        assert {k for k, _ in DC.iter_all()} == {'a', 'b'}


class TestPersistenceJsonBackend:
    def test_roundtrip(self, tmp_path, DC):
        p = Persistence(str(tmp_path / 'persist.json'), backend='json')
        p.upsert('Thing', 'x', {'v': 1})
        assert p.load('Thing', 'x') == {'v': 1}
        assert list(p.iter('Thing')) == [('x', {'v': 1})]
        p.delete('Thing', 'x')
        assert p.load('Thing', 'x') is None
        p.close()

    def test_binds_to_dc(self, tmp_path, DC):
        DC.bind_db(Persistence(str(tmp_path / 'persist.json'), backend='json'))
        DC(data={'name': 'x', 'v': 3}).persist()
        assert DC.load('x') == {'name': 'x', 'v': 3}

    def test_unknown_backend_raises(self, tmp_path):
        with pytest.raises(ValueError):
            Persistence(str(tmp_path / 'p'), backend='nope')
