"""Persistent cache for status line data (transcripts by file signature + git TTL)."""

import tempfile
import time
from collections import Counter

from gppu.data import Cache
from gppu.gppu import Path
from gppu.handlers import probe

CACHE_DIR = Path(tempfile.gettempdir()) / "claude_statusline_cache"
# Bump when the meaning of a cached count changes. v4: counts from the session record's
# messages, with no system or compaction count; v3 read every line, v2 from a byte offset.
SCHEMA = "v4"

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
            "cache_read": 0, "cache_create": 0, "errors": 0}


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


def _read(path):
    """Counts of one whole transcript, from the session record gppu.handlers parses: (tools, counts, meta, subagent).

    Everything comes from the record's messages, each one's data being its line: the session's
    first and last time, its version, cwd and branch from the first meta line, prompts, replies,
    tools, errors and tokens.
    """
    record = probe(path).parse(path)
    tools = Counter()
    counts = _new_counts()
    meta = _new_meta()
    for m in record["messages"]:
        e = m["data"]
        msg = e["message"]
        meta["first_ts"] = meta["first_ts"] or e["timestamp"]
        meta["last_ts"] = e["timestamp"]
        if e.get("isMeta") and not meta["version"]:
            meta.update(version=e.get("version", ""), cwd=e.get("cwd", ""), branch=e.get("gitBranch", ""))
        # Not m["subtype"] == "user": a subagent's first line carries its prompt beside a
        # tool result, which the handler calls a tool_result and the status line a prompt.
        if e["type"] == "user" and not e.get("isMeta") and _is_user_prompt(msg):
            counts["user"] += 1
        elif e["type"] == "assistant":
            counts["assistant"] += 1
            for block in msg.get("content", []):
                if block.get("type") == "tool_use":
                    tools[block.get("name", "?")] += 1
                elif block.get("type") == "text" and block.get("text", "").startswith(("Error:", "❌")):
                    counts["errors"] += 1
            u = msg.get("usage", {})
            counts["input"] += u.get("input_tokens", 0)
            counts["output"] += u.get("output_tokens", 0)
            counts["cache_read"] += u.get("cache_read_input_tokens", 0)
            counts["cache_create"] += u.get("cache_creation_input_tokens", 0)
    return dict(tools), counts, meta, record["data"]["subagent"]


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
    """Read the transcript and its subagents through gppu.handlers, each file again only when it changed.

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

    tools, counts, meta, spawned = Counter(), _new_counts(), _new_meta(), 0
    for fpath in [Path(path), *subagents]:
        # Per-file entries: no expiration (ttl=0), re-read whole when the file's signature changes.
        # An empty file is one Claude Code has just created: nothing to read yet.
        st = fpath.stat()
        if not st.st_size:
            continue
        file_key = f"jsonl:{SCHEMA}:{fpath}"
        sig = [st.st_size, st.st_mtime_ns]
        entry = _dc.get(file_key)
        if not entry or entry["sig"] != sig:
            new_tools, new_counts, new_meta, subagent = _read(fpath)
            entry = {"sig": sig, "tools": new_tools, "counts": new_counts, "meta": new_meta, "subagent": subagent}
            _dc.set(file_key, entry, ttl=0)
        tools.update(entry["tools"])
        counts = _merge_counts(counts, entry["counts"])
        meta = _merge_meta(meta, entry["meta"])
        spawned += entry["subagent"]

    _dc.set(session_key, {
        "ts": now, "tools": dict(tools), "counts": counts,
        "meta": meta, "subagents": spawned,
    }, ttl=0)
    return tools, counts, meta, spawned
