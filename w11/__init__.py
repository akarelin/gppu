"""w11 — Windows 11 utilities and diagnostics."""
__version__ = "0.1"

import os
import shutil
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    _DEFAULT_CONFIG = Path(sys._MEIPASS) / 'default_config'
else:
    _DEFAULT_CONFIG = Path(__file__).resolve().parent / 'default_config'
_USER_CONFIG = Path.home() / '.gppu' / 'w11'


def resolve_app_dir() -> Path:
    """Resolve the w11 config directory.

    Priority:
    1. W11_APP_DIR env var (set by dotfiles/chezmoi — points to source repo)
    2. ~/.gppu/w11 (manual install — bootstrapped from default_config/)
    """
    env_dir = os.environ.get('W11_APP_DIR')
    if env_dir:
        return Path(env_dir)

    if not _USER_CONFIG.exists():
        _USER_CONFIG.mkdir(parents=True, exist_ok=True)
        src = _DEFAULT_CONFIG if _DEFAULT_CONFIG.exists() else Path(__file__).resolve().parent
        for f in src.glob('*.yaml'):
            shutil.copy2(f, _USER_CONFIG / f.name)

    return _USER_CONFIG
