"""Git status of the working directory, for the status line."""

import subprocess

from gppu import Warn
from gppu.gppu import Path


def _run(args, cwd=None):
    """The command's output; empty when git answers no (not a repository, no upstream)."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=2)
    except (OSError, subprocess.TimeoutExpired) as e:
        Warn("git did not answer", " ".join(args), e)
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def git_info(cwd):
    """Collect git status for a working directory.

    Returns dict with: branch, dirty, stash, ahead, behind, repo_name, remotes.
    """
    info = {"branch": "", "dirty": False, "stash": 0, "ahead": 0, "behind": 0,
            "repo_name": "", "remotes": []}
    git = ["git", "-C", cwd]
    if not cwd or not _run([*git, "rev-parse", "--git-dir"]):
        return info
    if toplevel := _run([*git, "rev-parse", "--show-toplevel"]):
        info["repo_name"] = Path(toplevel).name
    info["branch"] = (_run([*git, "symbolic-ref", "--short", "HEAD"])
                      or _run([*git, "rev-parse", "--short", "HEAD"]))
    info["dirty"] = bool(_run([*git, "status", "--porcelain", "-uno"]))
    info["stash"] = len(_run([*git, "stash", "list"]).splitlines())
    ab = _run([*git, "rev-list", "--left-right", "--count", "HEAD...@{upstream}"]).split()
    if len(ab) == 2:
        info["ahead"], info["behind"] = int(ab[0]), int(ab[1])
    remotes = {}
    for line in _run([*git, "remote", "-v"]).splitlines():
        parts = line.split()
        if len(parts) >= 2 and "(fetch)" in line:
            name, url = parts[0], parts[1]
            if ":" in url and "@" in url:
                url = url.split(":")[-1]
            elif "://" in url:
                url = "/".join(url.split("/")[-2:])
            remotes[name] = url.removesuffix(".git")
    info["remotes"] = list(remotes.items())
    return info
