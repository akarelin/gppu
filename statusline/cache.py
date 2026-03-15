"""Persistent cache for status line data (JSONL incremental + git TTL)."""

import json
import os
import tempfile
import time
from collections import Counter

DEFAULT_CACHE_PATH = os.path.join(tempfile.gettempdir(), "claude_statusline_cache.json")
DEFAULT_GIT_TTL = 10  # seconds
DEFAULT_JSONL_TTL = 2  # seconds

_cache_path = DEFAULT_CACHE_PATH
_git_ttl = DEFAULT_GIT_TTL
_jsonl_ttl = DEFAULT_JSONL_TTL


def init_cache(cfg):
    """Initialize cache settings from config dict."""
    global _cache_path, _git_ttl, _jsonl_ttl
    _cache_path = cfg.get("cache_path", DEFAULT_CACHE_PATH)
    _git_ttl = cfg.get("git_ttl", DEFAULT_GIT_TTL)
    _jsonl_ttl = cfg.get("jsonl_ttl", DEFAULT_JSONL_TTL)


def _load():
    try:
        with open(_cache_path) as f:
            return json.load(f)
    except Exception:
        return {"jsonl": {}, "git": {}}


def _save(cache):
    try:
        with open(_cache_path, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _new_counts():
    return {"user": 0, "assistant": 0, "input": 0, "output": 0,
            "cache_read": 0, "cache_create": 0, "system": 0,
            "compactions": 0, "errors": 0}


def _new_meta():
    return {"version": "", "cwd": "", "branch": "", "first_ts": "", "last_ts": ""}


def _parse_from_offset(path, offset):
    """Parse JSONL from byte offset, return (tools_dict, counts_dict, meta_dict, new_offset)."""
    tools = Counter()
    counts = _new_counts()
    meta = _new_meta()
    try:
        size = os.path.getsize(path)
        if size <= offset:
            return {}, counts, meta, offset
        with open(path) as f:
            f.seek(offset)
            for line in f:
                try:
                    e = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                t = e.get("type")
                ts = e.get("timestamp", "")
                if ts:
                    if not meta["first_ts"]:
                        meta["first_ts"] = ts
                    meta["last_ts"] = ts
                if t == "user":
                    counts["user"] += 1
                    # First meta entry has version/cwd
                    if e.get("isMeta") and not meta["version"]:
                        meta["version"] = e.get("version", "")
                        meta["cwd"] = e.get("cwd", "")
                        meta["branch"] = e.get("gitBranch", "")
                elif t == "system":
                    counts["system"] += 1
                    if e.get("isMeta") and not meta["version"]:
                        meta["version"] = e.get("version", "")
                        meta["cwd"] = e.get("cwd", "")
                        meta["branch"] = e.get("gitBranch", "")
                elif t == "assistant":
                    counts["assistant"] += 1
                    msg = e.get("message")
                    if isinstance(msg, dict):
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tools[block.get("name", "?")] += 1
                        u = msg.get("usage", {})
                        counts["input"] += u.get("input_tokens", 0)
                        counts["output"] += u.get("output_tokens", 0)
                        counts["cache_read"] += u.get("cache_read_input_tokens", 0)
                        counts["cache_create"] += u.get("cache_creation_input_tokens", 0)
                    # Check for error content
                    if isinstance(msg, dict):
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "text":
                                txt = block.get("text", "")
                                if txt.startswith("Error:") or txt.startswith("❌"):
                                    counts["errors"] += 1
                if e.get("subtype") == "compact_boundary":
                    counts["compactions"] += 1
            new_offset = f.tell()
    except Exception:
        return dict(tools), counts, meta, offset
    return dict(tools), counts, meta, new_offset


def _merge_counts(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in _new_counts()}


def _merge_meta(a, b):
    """Merge meta: keep earliest first_ts, latest last_ts, first non-empty values."""
    return {
        "version": a.get("version") or b.get("version", ""),
        "cwd": a.get("cwd") or b.get("cwd", ""),
        "branch": a.get("branch") or b.get("branch", ""),
        "first_ts": min(a.get("first_ts", "") or "Z", b.get("first_ts", "") or "Z").rstrip("Z") or "",
        "last_ts": max(a.get("last_ts", ""), b.get("last_ts", "")),
    }


def _merge_tools(a, b):
    merged = Counter(a)
    merged.update(b)
    return dict(merged)


def transcript_stats_cached(path):
    """Incrementally parse JSONL + subagents with caching.

    Returns (Counter of tools, counts dict, meta dict, subagent_count).
    """
    if not path or not os.path.isfile(path):
        return Counter(), _new_counts(), _new_meta(), 0

    cache = _load()
    jsonl_cache = cache.setdefault("jsonl", {})

    # Check JSONL-level TTL: skip all file checks if recently validated
    now = time.time()
    session_key = f"_session:{path}"
    session_cached = jsonl_cache.get(session_key)
    if session_cached and (now - session_cached.get("ts", 0)) < _jsonl_ttl:
        return (Counter(session_cached["tools"]), session_cached["counts"],
                session_cached.get("meta", _new_meta()), session_cached.get("subagents", 0))

    # Collect all files to parse (main + subagents)
    files = [path]
    session_dir = path.removesuffix(".jsonl")
    subagents_dir = os.path.join(session_dir, "subagents")
    subagent_count = 0
    if os.path.isdir(subagents_dir):
        for fname in os.listdir(subagents_dir):
            if fname.endswith(".jsonl"):
                files.append(os.path.join(subagents_dir, fname))
                subagent_count += 1

    all_tools = Counter()
    all_counts = _new_counts()
    all_meta = _new_meta()

    for fpath in files:
        if not os.path.isfile(fpath):
            continue
        size = os.path.getsize(fpath)
        cached = jsonl_cache.get(fpath)

        if cached and cached["offset"] >= size:
            # File unchanged, use cache
            all_tools.update(cached["tools"])
            all_counts = _merge_counts(all_counts, cached["counts"])
            all_meta = _merge_meta(all_meta, cached.get("meta", _new_meta()))
        else:
            # Parse new data from offset
            old_offset = cached["offset"] if cached else 0
            old_tools = cached["tools"] if cached else {}
            old_counts = cached["counts"] if cached else _new_counts()
            old_meta = cached.get("meta", _new_meta()) if cached else _new_meta()

            new_tools, new_counts, new_meta, new_offset = _parse_from_offset(fpath, old_offset)

            merged_tools = _merge_tools(old_tools, new_tools)
            merged_counts = _merge_counts(old_counts, new_counts)
            merged_meta = _merge_meta(old_meta, new_meta)

            jsonl_cache[fpath] = {
                "offset": new_offset,
                "tools": merged_tools,
                "counts": merged_counts,
                "meta": merged_meta,
            }

            all_tools.update(merged_tools)
            all_counts = _merge_counts(all_counts, merged_counts)
            all_meta = _merge_meta(all_meta, merged_meta)

    # Store session-level aggregated result with TTL
    jsonl_cache[session_key] = {
        "ts": now, "tools": dict(all_tools), "counts": all_counts,
        "meta": all_meta, "subagents": subagent_count,
    }
    cache["jsonl"] = jsonl_cache
    _save(cache)
    return all_tools, all_counts, all_meta, subagent_count


def git_info_cached(cwd, git_fn):
    """Cache git_info results with TTL.

    Args:
        cwd: working directory
        git_fn: callable that takes cwd and returns git info dict
    """
    if not cwd:
        return git_fn(cwd)

    cache = _load()
    git_cache = cache.setdefault("git", {})
    cached = git_cache.get(cwd)

    now = time.time()
    if cached and (now - cached.get("ts", 0)) < _git_ttl:
        return cached["data"]

    data = git_fn(cwd)
    git_cache[cwd] = {"ts": now, "data": data}
    cache["git"] = git_cache
    _save(cache)
    return data
