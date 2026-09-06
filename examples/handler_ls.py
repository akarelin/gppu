#!/usr/bin/env python3
"""Print gppufs metadata for the configured location and its descendants."""

from __future__ import annotations

import json
from pathlib import Path

from gppu import Env
from gppu.handlers import GppuFileSystem


def filesystem() -> GppuFileSystem:
  Env.from_env(name='handlers', app_path=Path(__file__).parent)
  return GppuFileSystem(location=Env.glob('location'))


def listing(gppufs: GppuFileSystem) -> str:
  return json.dumps([gppufs.info(), *gppufs.ls(recurse=True)], indent=2, ensure_ascii=False)


def main() -> None:
  print(listing(filesystem()))


if __name__ == '__main__':
  main()
