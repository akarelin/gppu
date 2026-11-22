"""OpenViking state for the status line.

Health is a TTL-cached GET /health; recall and capture come from the JSON
snapshots the OV hooks write under $OPENVIKING_HOME/state/.
"""

import os
import time
import urllib.request

from gppu import Env, Warn
from gppu.gppu import Path, dict_from_json

from cache import cached

PROBE_TIMEOUT = 1.0      # s — matches OV's own probe budget; a timeout reads as "slow", not "off"
STATE_MAX_AGE = 30 * 60  # s — older snapshots read as absent


def _env(*names):
    """The first of OpenViking's own environment variables that is set; OV defines them, not the status line."""
    return next((os.environ[n].strip() for n in names if n in os.environ and os.environ[n].strip()), None)


def _ov_home():
    home = _env("OPENVIKING_HOME")
    return Path(home).expanduser() if home else Env.home / ".openviking"


def _read_json(path):
    """The file's JSON; None when the file is absent, which is OV not having written it."""
    if not Path(path).is_file():
        return None
    try:
        return dict_from_json(path)
    except ValueError as e:
        Warn("unreadable OpenViking file", path, e)
        return None


def _read_state(name, max_age=STATE_MAX_AGE):
    d = _read_json(_ov_home() / "state" / name)
    if not isinstance(d, dict):
        return None
    ts = d.get("ts")
    if max_age and isinstance(ts, (int, float)) and time.time() - ts / 1000 > max_age:
        return None
    return d


def _conf():
    """Connection settings in OV's own order: env > ovcli.conf > ov.conf. None when OV is not configured."""
    cli = _read_json(_env("OPENVIKING_CLI_CONFIG_FILE") or _ov_home() / "ovcli.conf")
    ov = _read_json(_env("OPENVIKING_CONFIG_FILE") or _ov_home() / "ov.conf")
    if cli is None and ov is None:
        return None
    cli, ov = cli or {}, ov or {}
    server = ov.get("server") or {}
    url = _env("OPENVIKING_URL", "OPENVIKING_BASE_URL") or cli.get("url") or server.get("url")
    if not url:
        # OV's own default when the config carries host/port instead of a URL.
        host = (server.get("host") or "127.0.0.1").replace("0.0.0.0", "127.0.0.1")
        url = f"http://{host}:{server.get('port', 1933)}"
    key = (_env("OPENVIKING_BEARER_TOKEN", "OPENVIKING_API_KEY")
           or cli.get("api_key") or server.get("root_api_key") or "")
    return url.rstrip("/"), key


def _probe(url, key):
    req = urllib.request.Request(f"{url}/health")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
            health = "ok" if 200 <= r.status < 300 else "off"
    except Exception as e:
        # Declared recovery: the failure is the reading. A timeout means the server may be
        # alive but lagging; urllib wraps socket timeouts in URLError.reason.
        health = "slow" if isinstance(getattr(e, "reason", e), TimeoutError) else "off"
    return {"health": health, "latency_ms": int((time.monotonic() - t0) * 1000)}


def ov_stats(session_id, probe_ttl):
    """OpenViking snapshot: health, last recall, and this session's capture."""
    conf = _conf()
    if not conf:
        return {}
    url, key = conf
    capture = _read_state("last-capture.json")
    return {
        **cached(f"ov:{url}", probe_ttl, lambda: _probe(url, key)),
        "recall": _read_state("last-recall.json"),
        "capture": capture if capture and capture.get("cc_session_id") == session_id else None,
    }
