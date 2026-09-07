#!/usr/bin/env python3
"""Print the catalog's Locations, or one Location and everything below it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gppu import Env
from gppu.handlers import GppuCatalog


def listing(gppufs: GppuCatalog, path: str | None = None) -> str:
  return json.dumps([gppufs.info(path), *gppufs.ls(path, recurse=path is not None)], indent=2)


def main() -> None:
  Env.from_env(name='handlers', app_path=Path(__file__).parent)
  print(listing(GppuCatalog(Env.glob('catalog')), *sys.argv[1:2]))


if __name__ == '__main__':
  main()
