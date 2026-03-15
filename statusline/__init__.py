"""Statusline - Claude Code 2-line status line tool."""
try:
    from importlib.metadata import version
    __version__ = version("gppu")
except Exception:
    __version__ = "0.0.0"
