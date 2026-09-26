import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'core'), *(str(p) for p in sorted((ROOT / 'providers').iterdir()) if p.is_dir())]

from gppu.connections import close_all  # noqa: E402
from gppu import Env  # noqa: E402


@pytest.fixture
def env():
  """Load a configuration dict; reset Env and open Connections afterwards."""
  def load(data: dict):
    Env.from_dict(data)
    return Env
  yield load
  close_all()
  Env.reset()
