"""
w11 — Windows 11 Superapp launcher.

Opens w11 sub-apps (events, onedrive, etc.) from a single TUI menu.
Each app declares a manifest in its own inline config (MANIFEST) describing modes and launch args.

Usage:
    python w11.py                  # interactive TUI launcher
    python w11.py events           # launch w11_events directly
    python w11.py onedrive         # launch w11-onedrive directly
    python w11.py --list           # list available apps
"""

from __future__ import annotations

from gppu import App
from gppu.tui import TUILauncher, launcher_main, load_app_registry
from w11 import resolve_app_dir

APP_DIR = resolve_app_dir()


class W11App(TUILauncher):
    TITLE = 'w11'
    MENU_TITLE = 'Windows 11 Tools'
    CONFIG = APP_DIR / 'w11.yaml'


def main() -> None:
    apps = load_app_registry(APP_DIR, App(config=W11App.CONFIG))   # w11 reads only its own w11.yaml, no environment
    launcher_main(apps, W11App, APP_DIR, 'w11 — Windows 11 Superapp')


if __name__ == '__main__':
    main()
