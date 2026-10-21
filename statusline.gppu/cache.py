"""Persistent cache for status line data (JSONL incremental + git TTL)."""

import json
import tempfile
import time
from collections import Counter

from gppu import Warn
from gppu.data import Cache
from gppu.gppu import Path

CACHE_DIR = Path(tempfile.gettempdir()) / "claude_statusline_cache"
# Bump when the meaning of a cached count changes: entries accumulate from a byte
# offset, so a parser fix cannot correct totals already stored under the old key.
SCHEMA = "v2"

_dc = Cache(str(CACHE_DIR), ttl=86400, backend='sqlite', skip_env='')


def cached(key, ttl, fn):
    """Return fn()'s result, re-running it only once the cached entry is older than ttl."""
    hit = _dc.get(key)
    now = time.time()
    if hit and now - hit["ts"] < ttl:
        return hit["data"]
    data = fn()
    _dc.set(key, {"ts": now, "data": data}, ttl=ttl * 3)
    return data


def _new_counts():
    return {"user": 0, "assistant": 0, "input": 0, "output": 0,
            "cache_read": 0, "cache_create": 0, "system": 0,
            "compactions": 0, "errors": 0}


def _new_meta():
    return {"version": "", "cwd": "", "branch": "", "first_ts": "", "last_ts": ""}


def _is_user_prompt(msg):
    """True when a type=user entry carries typed text rather than a tool result.

    Every tool result is recorded as a user-role message, so counting entries by
    type alone reports tool traffic, not turns.
    """
    if not isinstance(msg, dict):
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") != "tool_result" for b in content)
    return False


def _parse_from_offset(path, offset):
    """Parse JSONL from byte offset, return (tools_dict, counts_dict, meta_dict, new_offset)."""
    tools = Counter()
    counts = _new_counts()
    meta = _new_meta()
    try:
        # Transcripts are UTF-8; the platform default (cp1252 on Windows) raises
        # mid-file, which aborts the parse without advancing the offset.
        with open(path, encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                t = e.get("type")
                if ts := e.get("timestamp", ""):
                    meta["first_ts"] = meta["first_ts"] or ts
                    meta["last_ts"] = ts
                if t in ("user", "system") and e.get("isMeta") and not meta["version"]:
                    meta.update(version=e.get("version", ""), cwd=e.get("cwd", ""), branch=e.get("gitBranch", ""))
                if t == "user" and not e.get("isMeta") and _is_user_prompt(e.get("message")):
                    counts["user"] += 1
                elif t == "system":
                    counts["system"] += 1
                elif t == "assistant":
                    counts["assistant"] += 1
                    msg = e.get("message")
                    if isinstance(msg, dict):
                        for block in msg.get("content", []):
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use":
                                tools[block.get("name", "?")] += 1
                            elif block.get("type") == "text" and block.get("text", "").startswith(("Error:", "❌")):
                                counts["errors"] += 1
                        u = msg.get("usage", {})
                        counts["input"] += u.get("input_tokens", 0)
                        counts["output"] += u.get("output_tokens", 0)
                        counts["cache_read"] += u.get("cache_read_input_tokens", 0)
                        counts["cache_create"] += u.get("cache_creation_input_tokens", 0)
                if e.get("subtype") == "compact_boundary":
                    counts["compactions"] += 1
            offset = f.tell()
    except Exception as e:
        # Declared recovery: keep what was read, leave the offset so the next render reads again.
        Warn("transcript parse stopped", path, e)
    return dict(tools), counts, meta, offset


def _merge_counts(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in _new_counts()}


def _merge_meta(a, b):
    """Merge meta: keep earliest first_ts, latest last_ts, first non-empty values."""
    return {
        "version": a["version"] or b["version"],
        "cwd": a["cwd"] or b["cwd"],
        "branch": a["branch"] or b["branch"],
        "first_ts": min(a["first_ts"] or "Z", b["first_ts"] or "Z").rstrip("Z"),
        "last_ts": max(a["last_ts"], b["last_ts"]),
    }


def transcript_stats_cached(path, ttl):
    """Incrementally parse JSONL + subagents with caching.

    Returns (Counter of tools, counts dict, meta dict, subagent_count).
    """
    if not path or not Path(path).is_file():
        return Counter(), _new_counts(), _new_meta(), 0

    # Session-level TTL: skip all file checks if recently validated
    now = time.time()
    session_key = f"session:{SCHEMA}:{path}"
    hit = _dc.get(session_key)
    if hit and now - hit["ts"] < ttl:
        return Counter(hit["tools"]), hit["counts"], hit["meta"], hit["subagents"]

    subagents_dir = Path(path.removesuffix(".jsonl")) / "subagents"
    subagents = list(subagents_dir.glob("*.jsonl")) if subagents_dir.is_dir() else []

    tools, counts, meta = Counter(), _new_counts(), _new_meta()
    for fpath in [Path(path), *subagents]:
        # Per-file offset entries: no expiration (ttl=0), invalidated by size check
        file_key = f"jsonl:{SCHEMA}:{fpath}"
        entry = _dc.get(file_key) or {"offset": 0, "tools": {}, "counts": _new_counts(), "meta": _new_meta()}
        if entry["offset"] < fpath.stat().st_size:
            new_tools, new_counts, new_meta, offset = _parse_from_offset(fpath, entry["offset"])
            entry = {
                "offset": offset,
                "tools": dict(Counter(entry["tools"]) + Counter(new_tools)),
                "counts": _merge_counts(entry["counts"], new_counts),
                "meta": _merge_meta(entry["meta"], new_meta),
            }
            _dc.set(file_key, entry, ttl=0)
        tools.update(entry["tools"])
        counts = _merge_counts(counts, entry["counts"])
        meta = _merge_meta(meta, entry["meta"])

    _dc.set(session_key, {
        "ts": now, "tools": dict(tools), "counts": counts,
        "meta": meta, "subagents": len(subagents),
    }, ttl=0)
    return tools, counts, meta, len(subagents)
