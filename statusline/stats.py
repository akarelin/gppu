#!/usr/bin/env python3
"""Extract statistics from Claude Code JSONL transcripts.

Aggregation scopes:
  - session:  single JSONL + its subagents
  - project:  all sessions under a ~/.claude/projects/<project_dir>/
  - folder:   all sessions started in a given working directory
  - global:   all sessions across all projects

When run standalone, dumps all stats as YAML to stdout.
"""

import glob
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timedelta

import yaml

CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")


# ── Git ──────────────────────────────────────────────────────────────────────

def _run(args, cwd=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=2)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def git_info(cwd):
    """Collect git status for a working directory.

    Returns dict with: branch, dirty, stash, ahead, behind, repo_name, remotes.
    """
    info = {"branch": "", "dirty": False, "stash": 0, "ahead": 0, "behind": 0,
            "repo_name": "", "remotes": []}
    if not cwd or not _run(["git", "-C", cwd, "rev-parse", "--git-dir"]):
        return info
    toplevel = _run(["git", "-C", cwd, "rev-parse", "--show-toplevel"])
    if toplevel:
        info["repo_name"] = os.path.basename(toplevel)
    info["branch"] = (
        _run(["git", "-C", cwd, "symbolic-ref", "--short", "HEAD"])
        or _run(["git", "-C", cwd, "rev-parse", "--short", "HEAD"])
    )
    status = _run(["git", "-C", cwd, "status", "--porcelain", "-uno"])
    info["dirty"] = bool(status)
    stash = _run(["git", "-C", cwd, "stash", "list"])
    info["stash"] = len(stash.splitlines()) if stash else 0
    ab = _run(["git", "-C", cwd, "rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
    if ab:
        p = ab.split()
        if len(p) == 2:
            info["ahead"], info["behind"] = int(p[0]), int(p[1])
    remote_out = _run(["git", "-C", cwd, "remote", "-v"])
    if remote_out:
        seen = {}
        for line in remote_out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "(fetch)" in line:
                name, url = parts[0], parts[1]
                short_url = url
                if ":" in url and "@" in url:
                    short_url = url.split(":")[-1]
                elif "://" in url:
                    short_url = "/".join(url.split("/")[-2:])
                seen[name] = short_url.removesuffix(".git")
        info["remotes"] = list(seen.items())
    return info


# ── Low-level parsing ────────────────────────────────────────────────────────

def _parse_jsonl(path, tools, counts, tokens):
    """Parse a single JSONL file, accumulating into tools Counter, counts dict, and tokens dict."""
    if not os.path.isfile(path):
        return
    try:
        with open(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                t = e.get("type")
                if t == "user":
                    counts["user"] += 1
                elif t == "assistant":
                    counts["assistant"] += 1
                    msg = e.get("message")
                    if isinstance(msg, dict):
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tools[block.get("name", "?")] += 1
                        u = msg.get("usage", {})
                        tokens["input"] += u.get("input_tokens", 0)
                        tokens["output"] += u.get("output_tokens", 0)
                        tokens["cache_read"] += u.get("cache_read_input_tokens", 0)
                        tokens["cache_create"] += u.get("cache_creation_input_tokens", 0)
                elif t == "system":
                    counts["system"] += 1
                if e.get("subtype") == "compact_boundary":
                    counts["compactions"] += 1
    except Exception:
        pass


def _session_meta(path):
    """Extract session metadata from JSONL (scans full file for timestamps)."""
    meta = {"cwd": "", "version": "", "branch": "", "session_id": "",
            "started": None, "ended": None}
    if not os.path.isfile(path):
        return meta
    try:
        with open(path) as f:
            first_ts = None
            last_ts = None
            for line in f:
                try:
                    e = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                ts = e.get("timestamp")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
                if not meta["cwd"] and e.get("cwd"):
                    meta["cwd"] = e["cwd"]
                    meta["version"] = e.get("version", "")
                    meta["branch"] = e.get("gitBranch", "")
                    meta["session_id"] = e.get("sessionId", "")
            if first_ts:
                meta["started"] = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
            if last_ts:
                meta["ended"] = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
    except Exception:
        pass
    return meta


def _new_counts():
    return {"user": 0, "assistant": 0, "system": 0, "compactions": 0}


def _new_tokens():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}


def _add_dict(dst, src):
    for k in dst:
        dst[k] += src.get(k, 0)


# ── Session stats ────────────────────────────────────────────────────────────

def session_stats(path):
    """Full stats for one session (main JSONL + subagents).

    Returns dict with: tools, counts, tokens, meta, subagent_count, path.
    """
    tools = Counter()
    counts = _new_counts()
    tokens = _new_tokens()
    meta = _session_meta(path)

    _parse_jsonl(path, tools, counts, tokens)

    subagent_count = 0
    session_dir = path.removesuffix(".jsonl")
    subagents_dir = os.path.join(session_dir, "subagents")
    if os.path.isdir(subagents_dir):
        for fname in os.listdir(subagents_dir):
            if fname.endswith(".jsonl"):
                _parse_jsonl(os.path.join(subagents_dir, fname), tools, counts, tokens)
                subagent_count += 1

    wall = timedelta()
    if meta["started"] and meta["ended"]:
        wall = meta["ended"] - meta["started"]

    return {
        "tools": tools, "counts": counts, "tokens": tokens, "meta": meta,
        "subagent_count": subagent_count, "wall": wall, "path": path,
    }


# ── Aggregate stats ─────────────────────────────────────────────────────────

def _empty_aggregate():
    return {"tools": Counter(), "counts": _new_counts(), "tokens": _new_tokens(),
            "sessions": 0, "wall": timedelta(), "subagents": 0, "paths": []}


def _accumulate(agg, ss):
    """Add session_stats result to aggregate."""
    if ss["counts"]["user"] == 0:
        return  # skip empty sessions
    agg["tools"] += ss["tools"]
    _add_dict(agg["counts"], ss["counts"])
    _add_dict(agg["tokens"], ss["tokens"])
    agg["sessions"] += 1
    agg["wall"] += ss["wall"]
    agg["subagents"] += ss["subagent_count"]
    agg["paths"].append(ss["path"])


# ── Discovery ────────────────────────────────────────────────────────────────

def find_all_sessions(base_dir=None):
    """Find all JSONL session files across all projects."""
    if base_dir is None:
        base_dir = CLAUDE_PROJECTS
    sessions = []
    for jsonl in glob.glob(os.path.join(base_dir, "**", "*.jsonl"), recursive=True):
        if "/subagents/" in jsonl:
            continue
        sessions.append(jsonl)
    return sorted(sessions, key=os.path.getmtime, reverse=True)


def project_key_from_path(path):
    """Extract project key from JSONL path like ~/.claude/projects/-home-alex-RAN/xxx.jsonl."""
    parts = path.split("/")
    for i, p in enumerate(parts):
        if p == "projects" and i + 1 < len(parts):
            return parts[i + 1]
    return "unknown"


def project_name_from_key(key):
    """Convert project key like -home-alex-RAN to display path home/alex/RAN."""
    return key.replace("-", "/").lstrip("/")


# ── Collect at different scopes ──────────────────────────────────────────────

def collect_all():
    """Collect stats organized by project, folder, and global.

    Returns dict:
        by_project:  {project_key: {aggregate + sessions_list + display_name}}
        by_folder:   {cwd_path: aggregate}
        grand:       aggregate
    """
    all_sessions = find_all_sessions()
    by_project = {}
    by_folder = {}
    grand = _empty_aggregate()

    for path in all_sessions:
        ss = session_stats(path)
        if ss["counts"]["user"] == 0:
            continue

        # By project (claude projects dir)
        pkey = project_key_from_path(path)
        if pkey not in by_project:
            by_project[pkey] = _empty_aggregate()
            by_project[pkey]["display_name"] = project_name_from_key(pkey)
            by_project[pkey]["session_details"] = []
        _accumulate(by_project[pkey], ss)
        by_project[pkey]["session_details"].append(ss)

        # By folder (cwd where session was started)
        cwd = ss["meta"]["cwd"]
        if cwd:
            if cwd not in by_folder:
                by_folder[cwd] = _empty_aggregate()
                by_folder[cwd]["folder"] = cwd
            _accumulate(by_folder[cwd], ss)

        # Grand
        _accumulate(grand, ss)

    return {"by_project": by_project, "by_folder": by_folder, "grand": grand}


def collect_for_project(project_key):
    """Collect stats for a single project key."""
    base = os.path.join(CLAUDE_PROJECTS, project_key)
    if not os.path.isdir(base):
        return _empty_aggregate()
    agg = _empty_aggregate()
    for jsonl in glob.glob(os.path.join(base, "*.jsonl")):
        if "/subagents/" in jsonl:
            continue
        ss = session_stats(jsonl)
        _accumulate(agg, ss)
    agg["display_name"] = project_name_from_key(project_key)
    return agg


def collect_for_folder(folder):
    """Collect stats for sessions started in a specific folder."""
    agg = _empty_aggregate()
    for path in find_all_sessions():
        ss = session_stats(path)
        if ss["meta"]["cwd"] == folder:
            _accumulate(agg, ss)
    agg["folder"] = folder
    return agg


# ── YAML serialization ──────────────────────────────────────────────────────

def _serialize_aggregate(agg):
    """Convert aggregate to YAML-serializable dict."""
    return {
        "sessions": agg["sessions"],
        "wall_seconds": int(agg["wall"].total_seconds()),
        "subagents": agg["subagents"],
        "counts": dict(agg["counts"]),
        "tokens": dict(agg["tokens"]),
        "tools": dict(agg["tools"].most_common()),
        "tool_calls": sum(agg["tools"].values()),
    }


def _serialize_session(ss):
    """Convert session_stats to YAML-serializable dict."""
    m = ss["meta"]
    return {
        "path": ss["path"],
        "started": m["started"].isoformat() if m["started"] else None,
        "ended": m["ended"].isoformat() if m["ended"] else None,
        "wall_seconds": int(ss["wall"].total_seconds()),
        "cwd": m["cwd"],
        "branch": m["branch"],
        "version": m["version"],
        "subagents": ss["subagent_count"],
        "counts": dict(ss["counts"]),
        "tokens": dict(ss["tokens"]),
        "tools": dict(ss["tools"].most_common()),
        "tool_calls": sum(ss["tools"].values()),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """Dump all session statistics as YAML."""
    data = collect_all()

    if not data["grand"]["sessions"]:
        print("# No JSONL sessions found.")
        return

    output = {
        "by_project": {},
        "by_folder": {},
        "grand": _serialize_aggregate(data["grand"]),
    }

    for pkey in sorted(data["by_project"]):
        agg = data["by_project"][pkey]
        entry = _serialize_aggregate(agg)
        entry["display_name"] = agg.get("display_name", pkey)
        if "session_details" in agg:
            entry["sessions_list"] = [_serialize_session(ss) for ss in agg["session_details"]]
        output["by_project"][pkey] = entry

    for folder in sorted(data["by_folder"],
                         key=lambda f: data["by_folder"][f]["wall"], reverse=True):
        agg = data["by_folder"][folder]
        output["by_folder"][folder] = _serialize_aggregate(agg)

    yaml.dump(output, sys.stdout, default_flow_style=False, sort_keys=False, allow_unicode=True)


if __name__ == "__main__":
    import sys
    main()
