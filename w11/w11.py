"""
w11 — Windows 11 Superapp launcher.

Opens w11 sub-apps (events, onedrive, etc.) from a single TUI menu.
Each app declares a manifest in its own YAML config describing modes and launch args.

Usage:
    python w11.py                  # interactive TUI launcher
    python w11.py events           # launch w11_events directly
    python w11.py onedrive         # launch w11-onedrive directly
    python w11.py --list           # list available apps
"""

from __future__ import annotations

from pathlib import Path

from gppu import Env
from gppu.tui import LauncherApp, launcher_main, load_app_registry

APP_DIR = Path(__file__).parent


class W11App(LauncherApp):
    TITLE = 'w11'
    MENU_TITLE = 'Windows 11 Tools'


def main() -> None:
    Env()
    Env.load()
    apps = load_app_registry(APP_DIR)
    launcher_main(apps, W11App, APP_DIR, 'w11 — Windows 11 Superapp')


if __name__ == '__main__':
    main()
