"""Mount the configured gppufs sources for desktop browsing, with no arguments: each location Linked Data knows that this host
reaches, with its index beside it, the sources its MANIFEST names, and the catalog through its API, as the Catalog folder."""

MANIFEST = r"""
  # Windows desktop browsing through gppufs. Source paths are read by gppufs.
  mount_point: 'G:'
  # Linked Data's API: every location it knows that this host reaches is a source too, named as Linked Data names it.
  ld: 'https://api.karel.in/ld/v1'
  # Where the catalog's API is, at /lake/catalog (gppu.fs.catalog), shown as the Catalog folder: Linked Data's locations, and in each what the catalog holds there.
  catalog: 'https://api.karel.in'
  sources:
    Lake: '\\s1\Lake'
"""

import httpx

from gppu import App, Info
from gppu.fs import catalog as locations
from gppu.fs.gppufs import GppuFileSystem
from gppu.fs.vfs import mount


class Desktop(App):
    def run(self):
        records = httpx.get(f"{self.my('ld')}/fs/locations", timeout=300).raise_for_status().json()['items']
        catalog = locations.catalog(records)
        sources = {catalog.locations[row['location']]['name']: f'gppu::{folder}' for folder, row in locations.reached(catalog).items()}
        sources |= {name: f'gppu::{location}' for name, location in self.my('sources').items()}
        sources['Catalog'] = GppuFileSystem(catalog=self.my('catalog')).catalog   # the one gppufs's catalog
        Info('Desktop', self.my('mount_point'), ', '.join(sources))
        mount(sources, self.my('mount_point'))


if __name__ == '__main__':
    Desktop(config=__file__).run()   # its own configuration is its MANIFEST
