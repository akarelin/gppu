#!/usr/bin/env python3
"""Print the catalog's Locations, or one Location and everything below it."""

from __future__ import annotations

MANIFEST = """
  # The catalog it starts at. Its locations.yaml lists the Locations and where each keeps its index.
  catalog: D:/TextLake/.catalog
"""

import json
import sys

from gppu import App
from gppu.fs.catalog import GppuCatalog


def listing(gppufs: GppuCatalog, path: str | None = None) -> str:
  return json.dumps([gppufs.info(path), *gppufs.ls(path, recurse=path is not None)], indent=2)


def main() -> None:
  app = App(config=__file__)   # its own configuration is its MANIFEST
  print(listing(GppuCatalog(app.my('catalog')), *sys.argv[1:2]))


if __name__ == '__main__':
  main()
