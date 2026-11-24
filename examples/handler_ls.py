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


class HandlerLs(App):
    """Its configuration is its MANIFEST; the first argument is the Location to list."""
    catalog: str

    def main(self) -> None: print(listing(GppuCatalog(self.catalog), *sys.argv[1:2]))


if __name__ == '__main__':
  HandlerLs().main()
