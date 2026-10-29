"""Mount the configured gppufs sources for desktop browsing, with no arguments: each location Linked Data knows that this host
reaches, with its index beside it, the sources desktop.yaml names, and the catalog through its API, as the Catalog folder."""
from pathlib import Path

import httpx

from gppu import App, Env, Info
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
    Env.from_env(name='desktop', app_path=Path(__file__).parent)
    Desktop().run()
