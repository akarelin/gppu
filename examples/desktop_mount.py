"""Mount the configured gppufs sources for desktop browsing, with no arguments: each location Linked Data knows that this host
reaches, with its index beside it, the sources desktop.yaml names, and the catalog through its API, as the Catalog folder."""
from pathlib import Path

from gppu import App, Env, Info
from gppu.fs.catalog import CatalogFileSystem
from gppu.fs.desktop import mount
from gppu.fs import GppuFileSystem
from gppu.ld import gppufs


class Desktop(App):
    def run(self):
        gppufs.connect(self.my('ld'))
        catalog = gppufs.catalog()
        folders = gppufs.reached(catalog)
        sources = {catalog.locations[row['location']]['name']: gppufs.filesystem(catalog, row['location'], folders)
                   for row in folders.values()}
        sources |= {name: GppuFileSystem(location) for name, location in self.my('sources').items()}
        sources['Catalog'] = CatalogFileSystem(self.my('catalog'))
        Info('Desktop', self.my('mount_point'), ', '.join(sources))
        mount(sources, self.my('mount_point'))


if __name__ == '__main__':
    Env.from_env(name='desktop', app_path=Path(__file__).parent)
    Desktop().run()
