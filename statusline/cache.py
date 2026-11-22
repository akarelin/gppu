"""Persistent cache for status line data (transcripts read incrementally from a byte offset + git TTL)."""

import json
import tempfile
from collections import Counter

from gppu.data import Cache
from gppu.gppu import Path

CACHE_DIR = Path(tempfile.gettempdir()) / "claude_statusline_cache"
# region - SCHEMA
# .. Bump when the meaning of a cached count changes: entries accumulate from a byte
# .. offset, so a parser fix cannot correct totals already stored under the old key.
# .. v6: offset only through the last complete line; no system count; a session entry is its result.
# endregion
SCHEMA = "v6"

_dc = Cache(str(CACHE_DIR), ttl=86400, backend='sqlite', skip_env='')


def cached(key, ttl, fn):
    """fn()'s result, which Cache keeps for ttl seconds."""
    # .. The key carries SCHEMA: an older status line writes its own entry shape to the same cache folder.
    key = f"{SCHEMA}:{key}"
    hit = _dc.get(key)
    if hit is not None:
        return hit
    data = fn()
    _dc.set(key, data, ttl=ttl)
    return data


def _new_counts():
    return {"user": 0, "assistant": 0, "input": 0, "output": 0,
            "cache_read": 0, "cache_create": 0, "compactions": 0, "errors": 0}


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
    """Parse the complete JSONL lines after byte offset: (tools, counts, meta, new_offset).

    new_offset is just past the last newline, so a line Claude Code is still writing is read next time.
    """
    tools = Counter()
    counts = _new_counts()
    meta = _new_meta()
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n") + 1
    for line in data[:end].splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            # .. a line a crashed writer left truncated; the lines after it still count
            continue
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        # .. any line's time: the session starts with its first line, attachments before the first prompt
        if ts := e.get("timestamp", ""):
            meta["first_ts"] = meta["first_ts"] or ts
            meta["last_ts"] = ts
        if t in ("user", "system") and e.get("isMeta") and not meta["version"]:
            meta.update(version=e.get("version", ""), cwd=e.get("cwd", ""), branch=e.get("gitBranch", ""))
        msg = e.get("message")
        if t == "user" and not e.get("isMeta") and _is_user_prompt(msg):
            counts["user"] += 1
        elif t == "assistant":
            counts["assistant"] += 1
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
    return dict(tools), counts, meta, offset + end


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
    """The transcript's counts, read again at most once per ttl seconds.

    Returns (Counter of tools, counts dict, meta dict, subagent_count).
    """
    if not path or not Path(path).is_file():
        return Counter(), _new_counts(), _new_meta(), 0
    return cached(f"session:{SCHEMA}:{path}", ttl, lambda: _read_session(path))


def _read_session(path):
    """Read the transcript and its subagents, each file only from where the last read stopped."""
    subagents_dir = Path(path.removesuffix(".jsonl")) / "subagents"
    subagents = list(subagents_dir.glob("*.jsonl")) if subagents_dir.is_dir() else []

    tools, counts, meta = Counter(), _new_counts(), _new_meta()
    for fpath in [Path(path), *subagents]:
        # region - per-file entries
        # .. No expiration (ttl=0). A file that grew is read from the stored offset;
        # .. one smaller than the offset was rewritten and is read again from the start.
        # endregion
        size = fpath.stat().st_size
        file_key = f"jsonl:{SCHEMA}:{fpath}"
        entry = _dc.get(file_key)
        if entry and entry["offset"] > size:
            entry = None
        if not entry or entry["offset"] < size:
            entry = entry or {"offset": 0, "tools": {}, "counts": _new_counts(), "meta": _new_meta()}
            new_tools, new_counts, new_meta, new_offset = _parse_from_offset(fpath, entry["offset"])
            entry = {
                "offset": new_offset,
                "tools": dict(Counter(entry["tools"]) + Counter(new_tools)),
                "counts": _merge_counts(entry["counts"], new_counts),
                "meta": _merge_meta(entry["meta"], new_meta),
            }
            _dc.set(file_key, entry, ttl=0)
        tools.update(entry["tools"])
        counts = _merge_counts(counts, entry["counts"])
        meta = _merge_meta(meta, entry["meta"])
    return tools, counts, meta, len(subagents)
