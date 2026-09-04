from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_generated_handler_reference_is_current() -> None:
  root = Path(__file__).resolve().parents[1]

  subprocess.run(
    [sys.executable, str(root / 'scripts' / 'generate_handlers_docs.py'), '--check'],
    cwd=root,
    check=True,
    capture_output=True,
    text=True,
  )
