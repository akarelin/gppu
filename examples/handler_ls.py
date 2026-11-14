#!/usr/bin/env python3
"""Print the catalog's Locations, or one Location and everything below it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gppu import App
from gppu.fs.catalog import GppuCatalog


def listing(gppufs: GppuCatalog, path: str | None = None) -> str:
  return json.dumps([gppufs.info(path), *gppufs.ls(path, recurse=path is not None)], indent=2)


def main() -> None:
  handlers = App(config=Path(__file__).with_name('handlers.yaml'))
  print(listing(GppuCatalog(handlers.my('catalog')), *sys.argv[1:2]))


if __name__ == '__main__':
  main()
