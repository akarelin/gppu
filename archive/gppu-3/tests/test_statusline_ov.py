"""OpenViking status line state: snapshot reads, staleness, session filtering, health."""

import json
import time
import urllib.error

import pytest

from statusline import ov


@pytest.fixture
def ov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENVIKING_HOME", str(tmp_path))
    monkeypatch.delenv("OPENVIKING_CLI_CONFIG_FILE", raising=False)
    monkeypatch.delenv("OPENVIKING_CONFIG_FILE", raising=False)
    for var in ("OPENVIKING_URL", "OPENVIKING_BASE_URL",
                "OPENVIKING_API_KEY", "OPENVIKING_BEARER_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "state").mkdir()
    return tmp_path


def _write(home, name, payload):
    (home / "state" / name).write_text(json.dumps(payload), encoding="utf-8")


def test_stale_state_reads_as_absent(ov_home):
    _write(ov_home, "last-recall.json", {"reason": "ok", "count": 3, "ts": time.time() * 1000})
    assert ov._read_state("last-recall.json")["count"] == 3
    _write(ov_home, "last-recall.json",
           {"reason": "ok", "count": 3, "ts": (time.time() - ov.STATE_MAX_AGE - 60) * 1000})
    assert ov._read_state("last-recall.json") is None


def test_unconfigured_yields_no_segments(ov_home):
    assert ov.ov_stats("s1", 5) == {}


def test_capture_filtered_to_current_session(ov_home, monkeypatch):
    (ov_home / "ovcli.conf").write_text(json.dumps({"url": "https://ov.example/"}), encoding="utf-8")
    monkeypatch.setattr(ov, "cached", lambda key, ttl, fn: {"health": "ok", "latency_ms": 12})
    now = time.time() * 1000
    _write(ov_home, "last-recall.json", {"reason": "ok", "count": 6, "ts": now})
    _write(ov_home, "last-capture.json", {"pending_tokens": 900, "cc_session_id": "other", "ts": now})

    assert ov.ov_stats("mine", 5)["capture"] is None
    _write(ov_home, "last-capture.json", {"pending_tokens": 900, "cc_session_id": "mine", "ts": now})
    stats = ov.ov_stats("mine", 5)
    assert stats["capture"]["pending_tokens"] == 900
    assert stats["health"] == "ok"
    assert stats["recall"]["count"] == 6


def test_probe_classifies_health(ov_home, monkeypatch):
    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(ov.urllib.request, "urlopen", lambda *a, **kw: _Resp())
    assert ov._probe("https://ov.example", "key")["health"] == "ok"

    def _raise(exc):
        def _f(*a, **kw):
            raise exc
        return _f

    monkeypatch.setattr(ov.urllib.request, "urlopen", _raise(TimeoutError()))
    assert ov._probe("https://ov.example", "")["health"] == "slow"
    monkeypatch.setattr(ov.urllib.request, "urlopen",
                        _raise(urllib.error.URLError(TimeoutError())))
    assert ov._probe("https://ov.example", "")["health"] == "slow"
    monkeypatch.setattr(ov.urllib.request, "urlopen",
                        _raise(urllib.error.URLError(ConnectionRefusedError())))
    assert ov._probe("https://ov.example", "")["health"] == "off"
